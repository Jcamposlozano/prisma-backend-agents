"""
Adapter: cliente OpenAI Chat Completions.

Hace el POST a /chat/completions con response_format=json_object, extrae el
text del primer choice y delega al safe_parse_maia_json para obtener un
MaiaResponse validado.

Parámetros (temperature/top_p/max_tokens) iguales al backend Node para
mantener paridad de salida.

Port de la función callOpenAI() en Westfield_agent/server/maia-core.ts.
"""

from __future__ import annotations

import httpx

from westfield_agent_back_python.application.sanitizers import safe_parse_maia_json
from westfield_agent_back_python.domain.responses import MaiaResponse

DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_BASE_URL = "https://api.openai.com/v1"


class OpenAIChatClient:
    """Implementa ChatClient (ver ports/chat_client.py)."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_BASE_URL,
        timeout_seconds: float = 60.0,
    ) -> None:
        if not api_key:
            raise ValueError("OPENAI_API_KEY ausente — no se puede crear el chat client.")
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds

    async def chat(self, messages: list[dict[str, str]]) -> MaiaResponse:
        payload = {
            "model": self._model,
            "messages": messages,
            "temperature": 0.6,
            "top_p": 0.95,
            "max_tokens": 800,
            "response_format": {"type": "json_object"},
        }

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

        return safe_parse_maia_json(text)
