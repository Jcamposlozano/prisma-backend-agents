"""
Configuración de un agente — shape de `agents/<agent_id>/config.json` en S3.

Es la fuente de verdad única de cada agente: qué prompt usa, qué vector
store tiene activo y con qué proveedor/modelo LLM responde. La ingesta
(repo Westfield_agent_ingest_python) escribe este archivo; el runtime solo
lo lee. El contrato JSON está documentado en el README de ambos repos.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class HardRule(BaseModel):
    """
    Regla determinista sobre la respuesta estructurada del agente.

    `when`: condiciones AND — key = path "state.<k>" o "structured.<k>",
            value = {operador: valor} (eq, ne, gt, gte, lt, lte, in, nin).
    `set`:  keys top-level a forzar en `structured` si todo `when` se cumple.

    El evaluador vive en application/hard_rules.py.
    """

    when: dict[str, dict[str, Any]] = Field(default_factory=dict)
    set: dict[str, Any] = Field(default_factory=dict)


class AgentConfig(BaseModel):
    """Config completa de un agente. Campos opcionales tienen defaults seguros."""

    # --- identidad ---
    agent_id: str
    agent_name: str

    # --- prompt activo ---
    prompt_id: str
    prompt_s3_uri: str

    # --- vector store activo (None = agente sin RAG, modo válido) ---
    vector_store_id: str | None = None
    vector_store_s3_uri: str | None = None

    # --- LLM (el provider se valida contra la fábrica en load-time) ---
    llm_provider: str = "openai"
    llm_model: str
    temperature: float = 0.6
    max_tokens: int = 800

    # --- retrieval (pisan los retrieval_defaults del manifest) ---
    top_k: int = 4
    min_similarity: float = 0.2

    # --- formato de respuesta ---
    # "json": el LLM recibe response_format=json_object; el runtime extrae la
    # key convencional "message" y hace passthrough del objeto en `structured`.
    # "text": la respuesta del LLM se devuelve tal cual en `message`.
    response_format: Literal["json", "text"] = "text"

    # --- fallback y anti-leak (opcionales, por agente) ---
    fallback_message: str | None = None
    leak_markers: list[str] = Field(default_factory=list)
    leak_replacement_message: str | None = None

    # --- reglas deterministas sobre la respuesta estructurada ---
    # El LLM trata las reglas del prompt como sugerencias; las mecánicas que
    # DEBEN cumplirse se declaran acá y el runtime las fuerza server-side.
    # Ver application/hard_rules.py para el shape y los operadores.
    hard_rules: list[HardRule] = Field(default_factory=list)

    # --- metadata libre del agente ---
    metadata: dict[str, Any] = Field(default_factory=dict)
