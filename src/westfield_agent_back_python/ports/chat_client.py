"""
Port: cliente de chat completions.

El use case ChatWithAgent depende de esta interfaz, no del cliente concreto.
Devuelve el texto CRUDO del modelo — el parsing (json/text según el
response_format del agente) es responsabilidad de la capa application
(sanitizers.parse_llm_output), no del adapter. Eso mantiene a los adapters
de proveedor (OpenAI, Anthropic, Azure, ...) como transporte puro y los hace
intercambiables vía adapters/llm_factory.py.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ChatClient(Protocol):
    """Convierte una lista de mensajes en el texto crudo de respuesta del modelo."""

    async def chat(self, messages: list[dict[str, str]]) -> str:
        """
        messages: lista al estilo OpenAI [{"role": "system|user|assistant", "content": "..."}]
        return:   texto crudo del primer choice (puede ser JSON si el agente
                  usa response_format=json — lo parsea la capa application).
        raises:   excepciones de transporte (timeouts, 4xx/5xx) — el caller decide
                  cómo manejarlas (típicamente, degradar a fallback).
        """
        ...
