"""
Modelos del endpoint conversacional multi-agente.

Shape del contrato HTTP (HU-001):
  POST /api/agents/{agent_id}/chat
  request:  {conversation_id, user_id, message, history, state?}
  response: {agent_id, conversation_id, message, structured?, sources, fallback, rag_used}

`state` es un dict libre que el prompt builder renderiza como bloque
`# Estado actual` — permite que agentes con mecánica de turnos (ej. Maia:
current_question / turns_for_current_question) la conserven vía prompt,
sin lógica específica en el runtime.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

ChatRole = Literal["user", "assistant"]


class ChatTurn(BaseModel):
    """Un turno del historial, estilo OpenAI messages."""

    role: ChatRole
    content: str


class ChatRequest(BaseModel):
    """Payload del endpoint conversacional."""

    conversation_id: str
    user_id: str
    message: str = ""
    history: list[ChatTurn] = Field(default_factory=list)
    state: dict[str, Any] | None = None


class SourceRef(BaseModel):
    """Referencia a un chunk usado como contexto (sin texto — solo metadata)."""

    doc_title: str
    doc_tag: str
    similarity: float


class ChatResponse(BaseModel):
    """Respuesta del runtime. `structured` solo si el agente usa response_format=json."""

    agent_id: str
    conversation_id: str
    message: str
    structured: dict[str, Any] | None = None
    sources: list[SourceRef] = Field(default_factory=list)
    fallback: bool = False
    rag_used: bool = False
