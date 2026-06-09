"""
Port: cliente de chat completions.

El use case AskMaia depende de esta interfaz, no del cliente concreto. Eso
permite tests sin tocar la red (mock) y swappear OpenAI por otro provider
(Azure, Anthropic, etc.) implementando la misma interfaz en adapters/.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from westfield_agent_back_python.domain.responses import MaiaResponse


@runtime_checkable
class ChatClient(Protocol):
    """Convierte una lista de mensajes en una MaiaResponse parseada."""

    async def chat(self, messages: list[dict[str, str]]) -> MaiaResponse:
        """
        messages: lista al estilo OpenAI [{"role": "system|user|assistant", "content": "..."}]
        return:   MaiaResponse ya parseado y sanitizado contra JSON malformado
                  (el adapter es quien aplica safeParseMaiaJson).
        raises:   excepciones de transporte (timeouts, 4xx/5xx) — el caller decide
                  cómo manejarlas (típicamente, degradar a fallback).
        """
        ...
