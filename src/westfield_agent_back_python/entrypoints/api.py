"""
Entrypoint HTTP — FastAPI app del runtime multi-agente y multi-tenant.

Es el composition root: `create_app()` construye el storage S3, el
AgentRegistry (carga lazy por (university_code, agent_id) con caché TTL) y
el use case ChatWithAgent, y los cuelga de `app.state`. Los handlers son
delgados — extraen el body, hacen rate limit y delegan.

Endpoints (convención del gateway de la plataforma):
  - GET  /api/v1/health                                                  → estado + agentes cargados
  - GET  /api/v1/universities/{university_code}/agents/{agent_id}/health → fuerza la carga de UN agente
  - POST /api/v1/universities/{university_code}/agents/{agent_id}/chat   → un turno de conversación

El segmento {university_code} es DINÁMICO: se mapea al prefijo S3 del tenant
(s3.prefix con placeholder, ej. "org={university_code}/agents") en cada
request. Una universidad nueva = una carpeta nueva en el bucket, sin tocar
código ni configuración.

Mapeo de errores (aislado por agente):
  - UniversityNotFoundError → 404 (slug inválido)
  - AgentNotFoundError → 404  (no existe config.json para ese agent_id)
  - AgentLoadError     → 503  (config corrupta, prompt ausente, provider desconocido)
  - rate limit         → 429
  - vector store roto NO es error: el turno responde 200 con rag_used=false
  - LLM caído NO es error: el turno responde 200 con fallback=true

`create_app(storage=...)` permite inyectar un ObjectStorage fake en tests —
ningún test toca AWS ni la red.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from westfield_agent_back_python.adapters.llm_factory import ProviderSettings
from westfield_agent_back_python.adapters.s3_object_storage import S3ObjectStorage
from westfield_agent_back_python.application.agent_registry import AgentRegistry
from westfield_agent_back_python.application.chat_with_agent import ChatWithAgent
from westfield_agent_back_python.domain.chat import ChatRequest, ChatResponse
from westfield_agent_back_python.domain.errors import (
    AgentLoadError,
    AgentNotFoundError,
    UniversityNotFoundError,
)
from westfield_agent_back_python.ports.object_storage import ObjectStorage
from westfield_agent_back_python.shared.config import load_config
from westfield_agent_back_python.shared.logger import get_logger
from westfield_agent_back_python.shared.rate_limit import RateLimiter

log = get_logger("westfield_agent_back_python.api")


def create_app(
    *,
    storage: ObjectStorage | None = None,
    config: dict[str, Any] | None = None,
) -> FastAPI:
    """Composition root. `storage`/`config` inyectables para tests."""
    cfg = config or load_config()
    service_name = cfg["project"].get("name", "westfield-agent-back-python")

    if storage is None:
        storage = S3ObjectStorage(bucket=cfg["s3"]["bucket"], region=cfg["s3"]["region"])

    provider_settings = ProviderSettings(
        api_keys={"openai": cfg["openai"].get("api_key")},
        base_urls={"openai": cfg["openai"].get("base_url", "https://api.openai.com/v1")},
    )
    if not cfg["openai"].get("api_key"):
        log.warning("🟡 Sin OPENAI_API_KEY → los agentes openai responderán su fallback_message.")

    registry = AgentRegistry(
        storage=storage,
        prefix=cfg["s3"]["prefix"],
        provider_settings=provider_settings,
        embedding_model_fallback=cfg["openai"]["embedding_model_fallback"],
        ttl_seconds=cfg["registry"]["ttl_seconds"],
        negative_ttl_seconds=cfg["registry"]["negative_ttl_seconds"],
    )
    chat_with_agent = ChatWithAgent(registry=registry)
    rate_limiter = RateLimiter(
        window_seconds=cfg["rate_limit"]["window_seconds"],
        max_requests=cfg["rate_limit"]["max_requests"],
    )

    app = FastAPI(title=service_name, version="0.2.0")
    app.state.registry = registry
    app.state.chat_with_agent = chat_with_agent

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg["service"]["cors_origins"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ------------------------------------------------------------- handlers

    @app.get("/api/v1/health")
    async def health() -> dict:
        """Ping + snapshot de los agentes cargados en esta instancia."""
        return {
            "ok": True,
            "runtime": "python",
            "s3_bucket": cfg["s3"]["bucket"],
            "agents": registry.snapshot(),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    router = APIRouter(
        prefix="/api/v1/universities/{university_code}/agents",
        tags=["Agents"],
    )

    @router.get("/{agent_id}/health")
    async def agent_health(university_code: str, agent_id: str) -> dict:
        """Fuerza la carga del agente y reporta su estado (404/503 si falla)."""
        runtime = await registry.get(university_code, agent_id)
        return {
            "university": university_code,
            "agent_id": agent_id,
            "ok": True,
            "agent_name": runtime.config.agent_name,
            "degraded": runtime.degraded,
            "llm_provider": runtime.config.llm_provider,
            "llm_model": runtime.config.llm_model,
            "prompt_id": runtime.config.prompt_id,
            "vector_store_id": runtime.config.vector_store_id,
            "chunks": runtime.chunk_count,
        }

    @router.post("/{agent_id}/chat", response_model=ChatResponse)
    async def chat(
        university_code: str, agent_id: str, body: ChatRequest, request: Request
    ) -> ChatResponse:
        """Un turno de conversación con el agente, con rate limit por IP+tenant+agente."""
        ip = _extract_ip(request)
        if rate_limiter.hit(f"{ip}:{university_code}:{agent_id}"):
            raise HTTPException(
                status_code=429,
                detail="Demasiadas solicitudes. Espera un minuto y vuelve a intentar.",
            )
        return await chat_with_agent(university_code, agent_id, body)

    app.include_router(router)

    # ------------------------------------------------- mapeo de errores HTTP

    @app.exception_handler(UniversityNotFoundError)
    async def university_not_found_handler(
        _: Request, exc: UniversityNotFoundError
    ) -> JSONResponse:
        return JSONResponse(status_code=404, content={"error": str(exc)})

    @app.exception_handler(AgentNotFoundError)
    async def agent_not_found_handler(_: Request, exc: AgentNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"error": str(exc)})

    @app.exception_handler(AgentLoadError)
    async def agent_load_error_handler(_: Request, exc: AgentLoadError) -> JSONResponse:
        log.error(f"✗ {exc}")
        return JSONResponse(status_code=503, content={"error": str(exc)})

    # Mismo shape de error que el resto ({"error": ...}) en vez del default
    # de FastAPI ({"detail": ...}).
    @app.exception_handler(HTTPException)
    async def http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})

    log.info(
        f"🟢 Runtime multi-agente listo — bucket s3://{cfg['s3']['bucket']}/"
        f"{cfg['s3']['prefix']}/ · TTL {cfg['registry']['ttl_seconds']}s"
    )
    return app


def _extract_ip(request: Request) -> str:
    """Mismo orden de precedencia que el backend Node: XFF → x-real-ip → peer."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    if request.client:
        return request.client.host
    return "local"


# Instancia module-level que levanta uvicorn (`main_api.py`).
app = create_app()
