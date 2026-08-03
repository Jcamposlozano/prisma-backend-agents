"""
Adapter: cliente de embeddings de OpenAI.

Devuelve vectores L2-normalizados (norma=1) — eso permite usar producto
punto como similitud coseno sin re-normalizar en cada request.

Por ahora sólo se usa para embeber la query del estudiante en cada turno
(batch de 1). La batch de ingesta vive en el proyecto Node — cuando se
porte la ingesta a Python (V2), `embed_texts` ya está listo.

Port de Westfield_agent/server/rag/embeddings.ts.
"""

from __future__ import annotations

import httpx
import numpy as np

DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_BASE_URL = "https://api.openai.com/v1"


class OpenAIEmbeddings:
    """Cliente async, reusable. Mantené una sola instancia por proceso."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str = DEFAULT_EMBEDDING_MODEL,
        base_url: str = DEFAULT_BASE_URL,
        timeout_seconds: float = 30.0,
    ) -> None:
        if not api_key:
            raise ValueError("OPENAI_API_KEY ausente — no se pueden generar embeddings.")
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embebe N textos en un solo request. Devuelve vectores L2-normalizados."""
        if not texts:
            return []

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            res = await client.post(
                f"{self._base_url}/embeddings",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self._api_key}",
                },
                json={"model": self._model, "input": texts},
            )

        if res.status_code >= 400:
            body = res.text[:300]
            raise RuntimeError(f"OpenAI embeddings {res.status_code}: {body}")

        data = res.json()
        items = sorted(data.get("data", []), key=lambda d: d.get("index", 0))
        return [_l2_normalize(item["embedding"]) for item in items]

    async def embed_one(self, text: str) -> list[float]:
        """Helper para el caso típico de embeber un único string."""
        vectors = await self.embed_texts([text])
        return vectors[0]


def _l2_normalize(vector: list[float]) -> list[float]:
    """Devuelve el vector dividido por su norma L2. Si la norma es 0, lo deja."""
    arr = np.asarray(vector, dtype=np.float64)
    norm = float(np.linalg.norm(arr))
    if norm == 0.0:
        return arr.tolist()
    return (arr / norm).tolist()
