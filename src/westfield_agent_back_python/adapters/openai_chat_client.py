"""
Adapter: cliente OpenAI Chat Completions.

Hace el POST a /chat/completions y devuelve el texto crudo del primer
choice. Los parámetros de generación (model/temperature/max_tokens/
response_format) vienen del config.json del agente — el AgentRegistry
construye UNA instancia por agente vía adapters/llm_factory.py.

El parsing del output (json/text) NO vive acá — ver
application/sanitizers.parse_llm_output. Así este adapter queda como
transporte puro y es intercambiable por otro proveedor.
"""

from __future__ import annotations

from typing import Literal

import httpx

DEFAULT_BASE_URL = "https://api.openai.com/v1"


class OpenAIChatClient:
    """Implementa ChatClient (ver ports/chat_client.py)."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = DEFAULT_BASE_URL,
        temperature: float = 0.6,
        max_tokens: int = 800,
        response_format: Literal["json", "text"] = "text",
        timeout_seconds: float = 60.0,
    ) -> None:
        if not api_key:
            raise ValueError("OPENAI_API_KEY ausente — no se puede crear el chat client.")
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._response_format = response_format
        self._timeout = timeout_seconds

    async def chat(self, messages: list[dict[str, str]]) -> str:
        payload: dict = {
            "model": self._model,
            "messages": messages,
            "temperature": self._temperature,
            "top_p": 0.95,
            "max_tokens": self._max_tokens,
        }
        if self._response_format == "json":
            payload["response_format"] = {"type": "json_object"}

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            res = await client.post(
                f"{self._base_url}/chat/completions",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self._api_key}",
                },
                json=payload,
            )

        if res.status_code >= 400:
            body = res.text[:300]
            raise RuntimeError(f"OpenAI {res.status_code}: {body}")

        data = res.json()
        choices = data.get("choices") or []
        text = ""
        if choices:
            message_obj = choices[0].get("message") or {}
            text = message_obj.get("content") or ""

        if not text:
            raise RuntimeError("Respuesta vacía de OpenAI")

        return text
