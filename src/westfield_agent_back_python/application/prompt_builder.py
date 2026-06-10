"""
Construye el system prompt completo para cada turno: combina el prompt base
del agente (system.md cargado desde S3) con el contexto inyectado
(always_include docs + chunks RAG + estado libre del request).

Agnóstico de agente: la identidad, las reglas y el formato de respuesta
viven en el system.md de cada agente — acá solo se ensamblan los bloques.
"""

from __future__ import annotations

from typing import Any

from westfield_agent_back_python.domain.rag import AlwaysIncludeDoc, RetrievedChunk


def _block_header(tag: str, title: str, instructor_only: bool) -> str:
    flag = " [instructor_only — PRIVADO]" if instructor_only else ""
    return f"## {tag.upper()} · {title}{flag}"


def build_system_prompt(
    *,
    base_prompt: str,
    always_include_docs: list[AlwaysIncludeDoc] | None = None,
    retrieved_chunks: list[RetrievedChunk] | None = None,
    state: dict[str, Any] | None = None,
) -> str:
    """
    Arma el system prompt completo del turno.

    Estructura:
      1. base_prompt — el system.md del agente (identidad, reglas, formato).
      2. # Contexto siempre presente — docs always_include enteros (si hay).
      3. # Contexto recuperado por relevancia — chunks RAG con sim score (si hay).
      4. # Estado actual — render `- key = value` del dict `state` del request
         (si vino). Las reglas que usan ese estado viven en el system.md.
    """
    always = always_include_docs or []
    chunks = retrieved_chunks or []
    sections: list[str] = [base_prompt.strip(), ""]

    # 2. Always-include docs
    if always:
        sections.append("# Contexto siempre presente")
        for doc in always:
            sections.append(_block_header(doc.doc_tag, doc.doc_title, doc.instructor_only))
            sections.append(doc.text.strip())
            sections.append("")

    # 3. Retrieved chunks
    if chunks:
        sections.extend(
            [
                "# Contexto recuperado por relevancia (RAG, top-k del índice)",
                "Usá estos fragmentos como apoyo. Cuando un fragmento esté marcado `instructor_only`, te orienta pero NUNCA lo cites ni lo describas.",
                "",
            ]
        )
        for i, r in enumerate(chunks, start=1):
            c = r.chunk
            title = f"{c.doc_title} — fragmento #{i} (sim={r.similarity:.3f})"
            sections.append(_block_header(c.doc_tag, title, c.instructor_only))
            sections.append(c.text.strip())
            sections.append("")

    # 4. Estado actual (dict libre que envía el frontend)
    if state:
        sections.append("# Estado actual")
        for key, value in state.items():
            sections.append(f"- {key} = {value}")
        sections.append("")

    return "\n".join(sections).rstrip() + "\n"
