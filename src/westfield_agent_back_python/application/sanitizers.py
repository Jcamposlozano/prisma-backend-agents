"""
Sanitizadores y parsers defensivos del shape de respuesta de OpenAI.

Port literal del bloque de utilidades de Westfield_agent/server/maia-core.ts.
Estas funciones son puras (sin I/O) y se testean fácil — la lógica anti-leak
y el parser defensivo son la primera línea de defensa contra:
  - filtraciones de `instructor_only` en el message del modelo
  - JSON malformado que devuelve OpenAI a pesar del `response_format`
  - valores fuera de rango en `current_question` o `rubric_level`
"""

from __future__ import annotations

import json
import re
from typing import Any

from westfield_agent_back_python.domain.responses import (
    CurrentQuestion,
    MaiaResponse,
    MaiaRubricLevel,
)

# Marcadores que sugieren que el modelo filtró texto de las notas del
# instructor en la respuesta visible al estudiante. Mismos strings que el
# Node — si la rúbrica/notas cambian, actualizá ambos lados.
NOTES_LEAK_MARKERS = [
    "Notas del instructor",
    "notas del profesor",
    "Vías de Respuesta",
    "Reflexiones que Puede Suscitar",
]

# Si looksLikeNotesLeak da True, esto reemplaza al message original.
LEAK_REPLACEMENT_MESSAGE = (
    "No puedo compartir el material interno del instructor. "
    "Volvamos a tu argumento: ¿qué evidencia concreta del caso lo sostiene?"
)

_VALID_RUBRIC_LEVELS: set[str] = {
    "muy_pobre",
    "pobre",
    "satisfactorio",
    "superior",
    "excelente",
}

# Regex para strippear backticks de markdown (```json ... ```) que el modelo
# a veces antepone aunque pidamos JSON puro.
_LEADING_FENCE = re.compile(r"^```(?:json)?\s*", re.IGNORECASE)
_TRAILING_FENCE = re.compile(r"\s*```\s*$", re.IGNORECASE)


def looks_like_notes_leak(text: str) -> bool:
    """True si el message parece estar filtrando contenido de instructor_only."""
    lower = text.lower()
    return any(marker.lower() in lower for marker in NOTES_LEAK_MARKERS)


def is_rubric_level(value: Any) -> bool:
    """True si el valor es uno de los 5 niveles de rúbrica conocidos."""
    return isinstance(value, str) and value in _VALID_RUBRIC_LEVELS


def clamp_question(value: Any) -> CurrentQuestion:
    """Clampa cualquier input a 1|2|3 — default a 1 si no es 2 ni 3."""
    if value == 2:
        return 2
    if value == 3:
        return 3
    return 1


def safe_parse_maia_json(raw: str) -> MaiaResponse:
    """
    Parsea defensivamente la salida cruda del LLM a un MaiaResponse válido.

    Estrategia:
      1. Strippear backticks de markdown si el modelo los puso.
      2. Intentar JSON.parse.
      3. Si falla, devolver un MaiaResponse con `message = texto crudo` y
         defaults seguros (rubric satisfactorio, q1, sin avance, sin cierre).
      4. Si tiene éxito, validar cada campo con clamp/typecheck.
    """
    stripped = _TRAILING_FENCE.sub("", _LEADING_FENCE.sub("", raw)).strip()

    try:
        obj = json.loads(stripped)
        if not isinstance(obj, dict):
            raise ValueError("Top-level no es un objeto JSON.")
    except (json.JSONDecodeError, ValueError):
        return MaiaResponse(
            message=stripped,
            rubric_level="satisfactorio",
            current_question=1,
            advance_to_next_question=False,
            is_final_summary=False,
            unresolved_points=[],
        )

    message = obj.get("message")
    if not isinstance(message, str):
        message = ""

    rubric_raw = obj.get("rubric_level")
    rubric_level: MaiaRubricLevel = rubric_raw if is_rubric_level(rubric_raw) else "satisfactorio"

    unresolved = obj.get("unresolved_points")
    if isinstance(unresolved, list):
        unresolved_points = [str(x) for x in unresolved[:10]]
    else:
        unresolved_points = []

    return MaiaResponse(
        message=message,
        rubric_level=rubric_level,
        current_question=clamp_question(obj.get("current_question")),
        advance_to_next_question=bool(obj.get("advance_to_next_question")),
        is_final_summary=bool(obj.get("is_final_summary")),
        unresolved_points=unresolved_points,
    )
