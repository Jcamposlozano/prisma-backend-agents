"""
Caso de uso central: askMaia.

Recibe el payload del cliente (history + studentInput + estado) y devuelve
una MaiaResponse. Encapsula:
  - Clamping defensivo de inputs (history slice, studentInput length, etc.).
  - Construcción del query de RAG y retrieve.
  - Llamada al chat client con prompt completo.
  - Sanitización anti-leak.
  - Red de seguridad: forzar avance si turns_for_current_question >= FORCE_ADVANCE_AT.
  - Fallback offline en caso de error u OpenAI ausente.

Hexagonal: el use case depende de dos puertos (ChatClient y Retriever)
inyectados por el composition root (entrypoints/api.py). No conoce httpx
ni el shape del índice — sólo los modelos del dominio.

Port literal de Westfield_agent/server/maia-core.ts.
"""

from __future__ import annotations

import logging

from westfield_agent_back_python.application.fallback import build_fallback_response
from westfield_agent_back_python.application.prompt_builder import (
    TurnState,
    build_system_prompt,
)
from westfield_agent_back_python.application.sanitizers import (
    LEAK_REPLACEMENT_MESSAGE,
    clamp_question,
    looks_like_notes_leak,
)
from westfield_agent_back_python.domain.rag import AlwaysIncludeDoc
from westfield_agent_back_python.domain.responses import (
    MaiaRequestBody,
    MaiaResponse,
    MaiaTurn,
)
from westfield_agent_back_python.ports.chat_client import ChatClient
from westfield_agent_back_python.ports.retriever import Retriever

log = logging.getLogger(__name__)

# Si el modelo no avanza tras esta cantidad de turnos sobre la misma pregunta,
# el backend lo fuerza (red de seguridad — paridad con el Node).
FORCE_ADVANCE_AT = 5

# Límites defensivos para evitar payloads abusivos.
MAX_HISTORY_TURNS = 30
MAX_STUDENT_INPUT_CHARS = 4000
MAX_RAG_QUERY_CHARS = 2000


class AskMaia:
    """
    Use case principal. Composable: las dependencias se inyectan por __init__.

    El chat_client es requerido (sin él no hay LLM, sólo fallback).
    El retriever es opcional (sin él, prompt base sin chunks RAG).
    """

    def __init__(
        self,
        *,
        chat_client: ChatClient | None,
        retriever: Retriever | None,
        always_include_docs: list[AlwaysIncludeDoc] | None = None,
    ) -> None:
        self._chat = chat_client
        self._retriever = retriever
        self._always_include = always_include_docs or []

    async def __call__(self, body: MaiaRequestBody) -> MaiaResponse:
        # 1) Sanitizar inputs y construir histórico efectivo
        history: list[MaiaTurn] = list(body.history or [])[-MAX_HISTORY_TURNS:]
        student_input = (body.studentInput or "")[:MAX_STUDENT_INPUT_CHARS]
        current_question = clamp_question(body.currentQuestion or 1)
        turns_for_current_question = max(0, int(body.turnsForCurrentQuestion or 0))

        full_history: list[MaiaTurn] = (
            history + [MaiaTurn(role="student", content=student_input)]
            if student_input
            else history
        )

        # 2) Sin chat client (≈ sin OPENAI_API_KEY) → fallback offline
        if self._chat is None:
            return build_fallback_response(full_history)

        try:
            # 3) RAG retrieval (best-effort: si falla, sigue sin chunks)
            rag_query = _build_rag_query(history, student_input)
            retrieved = []
            if self._retriever is not None and rag_query:
                try:
                    retrieved = await self._retriever.retrieve(rag_query)
                except Exception:
                    log.exception("Retriever falló — sigo sin RAG")

            # 4) Armar system prompt + mensajes y llamar al LLM
            system_prompt = build_system_prompt(
                always_include_docs=self._always_include,
                retrieved_chunks=retrieved,
                turn_state=TurnState(
                    current_question=current_question,
                    turns_for_current_question=turns_for_current_question,
                ),
            )

            messages = [{"role": "system", "content": system_prompt}]
            for turn in history:
                role = "user" if turn.role == "student" else "assistant"
                messages.append({"role": role, "content": turn.content})

            if student_input:
                messages.append({"role": "user", "content": student_input})
            elif not history:
                messages.append({"role": "user", "content": "Hola Maia, vamos a empezar."})

            result = await self._chat.chat(messages)

            # 5) Sanitizar leak de notas del instructor
            if looks_like_notes_leak(result.message):
                result.message = LEAK_REPLACEMENT_MESSAGE

            # 6) Red de seguridad: forzar avance/cierre si pasa de FORCE_ADVANCE_AT
            if turns_for_current_question >= FORCE_ADVANCE_AT:
                if current_question < 3 and not result.advance_to_next_question:
                    result.advance_to_next_question = True
                if current_question == 3 and not result.is_final_summary:
                    result.is_final_summary = True

            return result

        except Exception as err:
            log.exception("Maia/OpenAI error — degradando a fallback")
            fb = build_fallback_response(full_history)
            fb.message = f"[error temporal con OpenAI] {fb.message}"
            return fb


def _build_rag_query(history: list[MaiaTurn], student_input: str) -> str:
    """
    Construye el query para el retriever combinando:
      - lo último que dijo el estudiante
      - el último turno de Maia (para mantener foco temático)
    """
    parts: list[str] = []
    if student_input:
        parts.append(student_input)
    for turn in reversed(history):
        if turn.role == "maia":
            parts.append(turn.content)
            break
    return "\n".join(parts)[:MAX_RAG_QUERY_CHARS]
