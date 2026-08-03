"""
Hard rules — reglas deterministas por agente sobre la respuesta estructurada.

Motivación (QA de Maia): las reglas de avance escritas en el prompt son
sugerencias para el LLM, no garantías — gpt-4o-mini las ignora con
frecuencia. Las mecánicas que DEBEN cumplirse (ej. "con N >= 3 turnos se
avanza de pregunta SIN EXCEPCIÓN") se declaran como `hard_rules` en el
config.json del agente y el runtime las aplica server-side DESPUÉS de
parsear la salida del modelo. El LLM sigue decidiendo el contenido
(message, rubric_level); las reglas solo fuerzan los flags de mecánica.

Es genérico: las condiciones leen del `state` del request y del
`structured` que devolvió el modelo; las acciones escriben en `structured`.
Ningún conocimiento específico de Maia vive en el runtime.

Shape en config.json:
  "hard_rules": [
    {
      "when": {
        "state.turns_for_current_question": {"gte": 3},
        "state.current_question": {"lte": 2}
      },
      "set": {"advance_to_next_question": true}
    }
  ]

- `when`: dict de condiciones AND. Key = path con prefijo "state." o
  "structured."; value = dict {operador: valor}. Operadores: eq, ne, gt,
  gte, lt, lte, in, nin. Path ausente → la condición NO se cumple.
- `set`: keys (top-level) a forzar en `structured` cuando todas las
  condiciones se cumplen.
- Las reglas se evalúan en orden, todas contra el MISMO snapshot de entrada
  (los `set` de una regla no afectan los `when` de las siguientes).
"""

from __future__ import annotations

import logging
from typing import Any

from westfield_agent_back_python.domain.agent import HardRule

log = logging.getLogger(__name__)

_OPS = {
    "eq": lambda actual, esperado: actual == esperado,
    "ne": lambda actual, esperado: actual != esperado,
    "gt": lambda actual, esperado: _es_numero(actual) and actual > esperado,
    "gte": lambda actual, esperado: _es_numero(actual) and actual >= esperado,
    "lt": lambda actual, esperado: _es_numero(actual) and actual < esperado,
    "lte": lambda actual, esperado: _es_numero(actual) and actual <= esperado,
    "in": lambda actual, esperado: isinstance(esperado, list) and actual in esperado,
    "nin": lambda actual, esperado: isinstance(esperado, list) and actual not in esperado,
}


def _es_numero(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _resolve(path: str, state: dict[str, Any], structured: dict[str, Any]) -> tuple[bool, Any]:
    """Devuelve (encontrado, valor) para un path 'state.x' o 'structured.y'."""
    root, _, key = path.partition(".")
    if not key:
        return False, None
    source = state if root == "state" else structured if root == "structured" else None
    if source is None or key not in source:
        return False, None
    return True, source[key]


def _rule_matches(rule: HardRule, state: dict[str, Any], structured: dict[str, Any]) -> bool:
    if not rule.when:
        return False  # regla sin condiciones: ignorada (un set incondicional es un bug de config)
    for path, condiciones in rule.when.items():
        encontrado, actual = _resolve(path, state, structured)
        if not encontrado:
            return False
        for op_name, esperado in condiciones.items():
            op = _OPS.get(op_name)
            if op is None:
                log.warning(f"hard_rules: operador desconocido {op_name!r} en {path!r} — regla ignorada")
                return False
            if not op(actual, esperado):
                return False
    return True


def apply_hard_rules(
    rules: list[HardRule],
    *,
    state: dict[str, Any] | None,
    structured: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, bool]:
    """
    Aplica las reglas y devuelve (structured_actualizado, hubo_override).

    Sin `structured` (agente en response_format=text) no hay nada que forzar.
    Las condiciones se evalúan contra el snapshot ORIGINAL; los sets se
    acumulan sobre una copia.
    """
    if not rules or structured is None:
        return structured, False

    snapshot_state = state or {}
    out = dict(structured)
    overridden = False
    for rule in rules:
        if _rule_matches(rule, snapshot_state, structured):
            for key, value in rule.set.items():
                if out.get(key) != value:
                    out[key] = value
                    overridden = True
    return out, overridden
