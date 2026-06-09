"""
Modelos de request/response del endpoint /api/maia.

Contratos públicos del servicio — el shape debe ser idéntico al del backend
Node (server/maia-core.ts). El frontend depende de estos campos para mover
la ProgressBar, RubricBadge y decidir si mostrar el resumen final.

Usamos Pydantic v2 para que FastAPI valide la request automáticamente y para
serializar la response sin código extra.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# Niveles válidos de la rúbrica de evaluación. Orden creciente de calidad.
MaiaRubricLevel = Literal[
    "muy_pobre",
    "pobre",
    "satisfactorio",
    "superior",
    "excelente",
]

# Qué pregunta de introspección está activa.
CurrentQuestion = Literal[1, 2, 3]


class MaiaTurn(BaseModel):
    """Un turno del histórico de la conversación. `student` o `maia`."""

    role: Literal["student", "maia"]
    content: str


class MaiaRequestBody(BaseModel):
    """Payload entrante a POST /api/maia."""

    history: list[MaiaTurn] = Field(default_factory=list)
    studentInput: str = ""
    # Estado que envía el cliente para que el motor pueda decidir avance.
    currentQuestion: CurrentQuestion | None = None
    turnsForCurrentQuestion: int | None = None


class MaiaResponse(BaseModel):
    """Respuesta del agente. Shape acoplado al frontend — no cambiar sin actualizar el cliente."""

    message: str
    rubric_level: MaiaRubricLevel
    current_question: CurrentQuestion
    advance_to_next_question: bool
    is_final_summary: bool
    unresolved_points: list[str] = Field(default_factory=list)
    # Marca opcional para que el frontend sepa que no hubo OpenAI (fallback).
    fallback: bool | None = None
