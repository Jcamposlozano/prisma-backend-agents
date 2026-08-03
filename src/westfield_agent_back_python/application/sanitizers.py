"""
Sanitizadores y parsers defensivos de la salida del LLM.

Funciones puras (sin I/O), agnósticas de agente:
  - parse_llm_output: parsea la salida cruda según el response_format del
    agente ("json" → (message, structured), "text" → (texto, None)). JSON
    malformado degrada a texto — nunca rompe el turno.
  - looks_like_leak: detección de filtraciones por marcadores configurables
    (config.json del agente: `leak_markers`).
"""

from __future__ import annotations

import json
import re
from typing import Any, Literal

# Regex para strippear backticks de markdown (```json ... ```) que el modelo
# a veces antepone aunque pidamos JSON puro.
_LEADING_FENCE = re.compile(r"^```(?:json)?\s*", re.IGNORECASE)
_TRAILING_FENCE = re.compile(r"\s*```\s*$", re.IGNORECASE)


def strip_markdown_fences(raw: str) -> str:
    """Quita fences ```json ... ``` del principio/final si están."""
    return _TRAILING_FENCE.sub("", _LEADING_FENCE.sub("", raw)).strip()


def parse_llm_output(
    raw: str, response_format: Literal["json", "text"]
) -> tuple[str, dict[str, Any] | None]:
    """
    Parsea defensivamente la salida cruda del LLM según el formato del agente.

    "text": devuelve (texto stripped, None).
    "json": intenta parsear; si el top-level es un dict, devuelve
            (obj["message"] si es string no vacío, si no el texto crudo, obj).
            JSON malformado o no-dict → degrada a modo text (texto, None).
    """
    stripped = strip_markdown_fences(raw)

    if response_format == "text":
        return stripped, None

    try:
        obj = json.loads(stripped)
    except json.JSONDecodeError:
        return stripped, None
    if not isinstance(obj, dict):
        return stripped, None

    message = obj.get("message")
    if not isinstance(message, str) or not message.strip():
        message = stripped
    return message, obj


def looks_like_leak(text: str, markers: list[str]) -> bool:
    """True si el texto contiene alguno de los marcadores de leak del agente."""
    if not markers:
        return False
    lower = text.lower()
    return any(marker.lower() in lower for marker in markers if marker)
