"""
Caso de uso central del runtime multi-agente: un turno de conversación.

Recibe (agent_id, ChatRequest) y devuelve un ChatResponse. Encapsula:
  - Resolución del agente vía AgentRegistry (carga lazy + caché + TTL).
  - Clamping defensivo de inputs (history slice, message length).
  - Query RAG y retrieve best-effort (si falla, sigue sin chunks).
  - Construcción del prompt final (system.md del agente + contexto + estado).
  - Llamada al LLM del agente y parsing según su response_format.
  - Anti-leak con los marcadores configurados por agente.
  - Fallback controlado si el LLM no está disponible o falla.

Hexagonal: depende del registry y de los ports (ChatClient, Retriever) que
viven dentro del AgentRuntime — no conoce httpx, boto3 ni FAISS.

AgentNotFoundError / AgentLoadError se propagan al entrypoint (404/503):
son condiciones del agente, no del turno.
"""

from __future__ import annotations

import logging

from westfield_agent_back_python.application.agent_registry import AgentRegistry, AgentRuntime
from westfield_agent_back_python.application.hard_rules import apply_hard_rules
from westfield_agent_back_python.application.prompt_builder import build_system_prompt
from westfield_agent_back_python.application.sanitizers import (
    looks_like_leak,
    parse_llm_output,
)
from westfield_agent_back_python.domain.chat import (
    ChatRequest,
    ChatResponse,
    ChatTurn,
    SourceRef,
)
from westfield_agent_back_python.domain.rag import RetrievedChunk

log = logging.getLogger(__name__)

# Límites defensivos para evitar payloads abusivos.
MAX_HISTORY_TURNS = 30
MAX_MESSAGE_CHARS = 4000
MAX_RAG_QUERY_CHARS = 2000

# Defaults si el config.json del agente no define los suyos.
DEFAULT_FALLBACK_MESSAGE = (
    "Estoy teniendo un problema técnico en este momento. "
    "Intentémoslo de nuevo en unos minutos."
)
DEFAULT_LEAK_REPLACEMENT_MESSAGE = (
    "No puedo compartir material interno. Sigamos con la conversación."
)

# Apertura sintética cuando el primer turno llega sin mensaje ni historial.
OPENING_USER_MESSAGE = "Hola, vamos a empezar."


class ChatWithAgent:
    """Use case principal. El registry se inyecta por el composition root."""

    def __init__(self, *, registry: AgentRegistry) -> None:
        self._registry = registry

    async def __call__(self, agent_id: str, body: ChatRequest) -> ChatResponse:
        # 1) Resolver el agente (puede tirar AgentNotFoundError/AgentLoadError).
        runtime = await self._registry.get(agent_id)
        config = runtime.config

        # 2) Clamps defensivos.
        history: list[ChatTurn] = list(body.history or [])[-MAX_HISTORY_TURNS:]
        message = (body.message or "")[:MAX_MESSAGE_CHARS]

        # 3) Sin chat client (sin API key del provider) → fallback controlado.
        if runtime.chat_client is None:
            return self._fallback(runtime, agent_id, body)

        # 4) RAG retrieval — best-effort: si falla, el turno sigue sin chunks.
        retrieved: list[RetrievedChunk] = []
        if runtime.retriever is not None:
            rag_query = _build_rag_query(history, message)
            if rag_query:
                try:
                    retrieved = await runtime.retriever.retrieve(rag_query)
                except Exception:
                    log.exception(f"Retriever de '{agent_id}' falló — sigo sin RAG")

        # 5) Prompt final + mensajes estilo OpenAI.
        system_prompt = build_system_prompt(
            base_prompt=runtime.system_prompt,
            always_include_docs=runtime.always_include,
            retrieved_chunks=retrieved,
            state=body.state,
        )
        messages = [{"role": "system", "content": system_prompt}]
        for turn in history:
            messages.append({"role": turn.role, "content": turn.content})
        if message:
            messages.append({"role": "user", "content": message})
        elif not history:
            messages.append({"role": "user", "content": OPENING_USER_MESSAGE})

        # 6) Llamada al LLM — si falla, fallback controlado (nunca 500).
        try:
            raw = await runtime.chat_client.chat(messages)
        except Exception:
            log.exception(f"LLM de '{agent_id}' falló — degradando a fallback")
            return self._fallback(runtime, agent_id, body)

        # 7) Parsing según response_format + hard rules + anti-leak por agente.
        text, structured = parse_llm_output(raw, config.response_format)

        # Las mecánicas declaradas en config.hard_rules se fuerzan server-side
        # — el prompt es una sugerencia para el LLM, esto es la garantía.
        structured, overridden = apply_hard_rules(
            config.hard_rules, state=body.state, structured=structured
        )
        if overridden:
            log.info(f"hard_rules de '{agent_id}' forzaron flags en structured")

        if looks_like_leak(text, config.leak_markers):
            text = config.leak_replacement_message or DEFAULT_LEAK_REPLACEMENT_MESSAGE
            if structured is not None:
                structured = {**structured, "message": text}

        # 8) Fuentes visibles — nunca exponer metadata de docs instructor_only.
        sources = [
            SourceRef(
                doc_title=r.chunk.doc_title,
                doc_tag=r.chunk.doc_tag,
                similarity=round(r.similarity, 4),
            )
            for r in retrieved
            if not r.chunk.instructor_only
        ]

        return ChatResponse(
            agent_id=agent_id,
            conversation_id=body.conversation_id,
            message=text,
            structured=structured,
            sources=sources,
            fallback=False,
            rag_used=bool(retrieved),
        )

    @staticmethod
    def _fallback(runtime: AgentRuntime, agent_id: str, body: ChatRequest) -> ChatResponse:
        """Respuesta plantillada cuando el LLM no está disponible o falló."""
        return ChatResponse(
            agent_id=agent_id,
            conversation_id=body.conversation_id,
            message=runtime.config.fallback_message or DEFAULT_FALLBACK_MESSAGE,
            structured=None,
            sources=[],
            fallback=True,
            rag_used=False,
        )


def _build_rag_query(history: list[ChatTurn], message: str) -> str:
    """
    Query del retriever: lo último que dijo el usuario + el último turno del
    asistente (para mantener foco temático).
    """
    parts: list[str] = []
    if message:
        parts.append(message)
    for turn in reversed(history):
        if turn.role == "assistant":
            parts.append(turn.content)
            break
    return "\n".join(parts)[:MAX_RAG_QUERY_CHARS]
