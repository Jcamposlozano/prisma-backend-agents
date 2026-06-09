"""
Entrypoint HTTP — FastAPI app.

Es el composition root: al startup carga config, intenta cargar el índice
RAG, construye los adapters (chat client + retriever) y los inyecta en el
use case AskMaia. Los handlers de las rutas son delgados — sólo extraen
el body, hacen rate limit y delegan en `app.state.ask_maia(body)`.

Endpoints (paridad de shape con el backend Node):
  - GET  /api/health  → ping + info de runtime
  - POST /api/maia    → orquesta el turno y devuelve MaiaResponse
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from westfield_agent_back_python.adapters.cosine_retriever import CosineRetriever
from westfield_agent_back_python.adapters.index_file_loader import load_index_from_disk
from westfield_agent_back_python.adapters.openai_chat_client import OpenAIChatClient
from westfield_agent_back_python.adapters.openai_embeddings import OpenAIEmbeddings
from westfield_agent_back_python.application.ask_maia import AskMaia
from westfield_agent_back_python.application.fallback import build_fallback_response
from westfield_agent_back_python.domain.responses import MaiaRequestBody, MaiaResponse
from westfield_agent_back_python.shared.config import load_config
from westfield_agent_back_python.shared.logger import get_logger
from westfield_agent_back_python.shared.rate_limit import RateLimiter

log = get_logger("westfield_agent_back_python.api")

cfg = load_config()
service_name = cfg["project"].get("name", "westfield-agent-back-python")
app = FastAPI(title=service_name, version="0.1.0")

# CORS — mismos orígenes que el backend Node.
app.add_middleware(
    CORSMiddleware,
    allow_origins=cfg["service"]["cors_origins"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],
)

# Rate limit instance — única por proceso.
_rate_limiter = RateLimiter(
    window_seconds=cfg["rate_limit"]["window_seconds"],
    max_requests=cfg["rate_limit"]["max_requests"],
)


@app.on_event("startup")
async def _startup() -> None:
    """
    Composition root: arma todas las dependencias y las inyecta en el use case.

    Estrategia:
      - Chat client: siempre creado si hay OPENAI_API_KEY. Sin key → None y
        el use case degrada a fallback offline.
      - RAG: best-effort. Si falta el índice o no se puede leer, el servicio
        igual arranca, sólo que sin contexto RAG (prompt base + fallback).
    """
    openai_cfg = cfg["maia"]["openai"]
    api_key = openai_cfg.get("api_key")

    # 1) Chat client
    chat_client = None
    if api_key:
        chat_client = OpenAIChatClient(
            api_key=api_key,
            model=openai_cfg["model"],
            base_url=openai_cfg["base_url"],
        )
        log.info(f"🟢 Chat client listo — modelo: {openai_cfg['model']}")
    else:
        log.warning("🟡 Sin OPENAI_API_KEY → /api/maia opera en modo fallback offline.")

    # 2) RAG (índice + retriever)
    retriever = None
    always_include = []
    rag_info = None
    try:
        index = load_index_from_disk(cfg["maia"]["index_path"])
        always_include = index.always_include
        rag_info = {
            "name": index.name,
            "chunks": len(index.chunks),
            "always_include": len(always_include),
            "embedding_model": index.embedding_model,
            "generated_at": index.generated_at,
        }
        if api_key:
            embeddings = OpenAIEmbeddings(
                api_key=api_key,
                model=openai_cfg["embedding_model"],
                base_url=openai_cfg["base_url"],
            )
            retriever = CosineRetriever(index=index, embeddings=embeddings)
        log.info(
            f"🧠 RAG cargado: contexto \"{index.name}\" · "
            f"{len(index.chunks)} chunks · {len(always_include)} always_include "
            f"({index.embedding_model})"
        )
    except Exception as err:
        log.warning(f"✗ RAG no cargó — Maia arranca SIN índice: {err}")

    # 3) Use case con dependencias inyectadas
    app.state.ask_maia = AskMaia(
        chat_client=chat_client,
        retriever=retriever,
        always_include_docs=always_include,
    )
    app.state.rag_info = rag_info
    app.state.openai_configured = bool(api_key)
    app.state.openai_model = openai_cfg["model"]

    host = cfg["service"]["host"]
    port = cfg["service"]["port"]
    log.info(f"🟢 Maia API listening on http://{host}:{port}")


@app.get("/api/health")
async def health() -> dict:
    """Ping + info de runtime — paridad con el backend Node."""
    return {
        "ok": True,
        "openaiConfigured": bool(getattr(app.state, "openai_configured", False)),
        "model": getattr(app.state, "openai_model", "gpt-4o-mini"),
        "rag": getattr(app.state, "rag_info", None),
        "runtime": "python",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/api/maia", response_model=MaiaResponse)
async def maia(body: MaiaRequestBody, request: Request) -> MaiaResponse:
    """Orquesta un turno del agente con rate limit por IP."""
    ip = _extract_ip(request)
    if _rate_limiter.hit(ip):
        raise HTTPException(
            status_code=429,
            detail="Demasiadas solicitudes. Espera un minuto y vuelve a intentar.",
        )

    ask_maia: AskMaia = app.state.ask_maia
    try:
        return await ask_maia(body)
    except Exception:
        # askMaia ya tiene fallback interno; este except es la red final por
        # si algo escapó (bug). Degradamos visiblemente para no romper la demo.
        log.exception("askMaia tiró pese al try interno — devuelvo fallback")
        fb = build_fallback_response(body.history or [])
        fb.message = f"[error inesperado en el servidor] {fb.message}"
        return fb


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


# Handler global para devolver el mismo shape de error que el Node, en lugar
# del default de FastAPI ({"detail": "..."}).
@app.exception_handler(HTTPException)
async def http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})
