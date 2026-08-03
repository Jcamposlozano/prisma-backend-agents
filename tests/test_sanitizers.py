"""Tests de los sanitizadores defensivos de la salida del LLM."""

from __future__ import annotations

import json

from westfield_agent_back_python.application.sanitizers import (
    looks_like_leak,
    parse_llm_output,
    strip_markdown_fences,
)


def test_parse_text_devuelve_texto_stripped_sin_structured() -> None:
    message, structured = parse_llm_output("  hola mundo  ", "text")
    assert message == "hola mundo"
    assert structured is None


def test_parse_json_happy_path() -> None:
    raw = json.dumps({"message": "Hola", "rubric_level": "superior", "extra": 42})
    message, structured = parse_llm_output(raw, "json")
    assert message == "Hola"
    assert structured == {"message": "Hola", "rubric_level": "superior", "extra": 42}


def test_parse_json_strippea_backticks() -> None:
    raw = '```json\n{"message": "Hi", "x": 1}\n```'
    message, structured = parse_llm_output(raw, "json")
    assert message == "Hi"
    assert structured == {"message": "Hi", "x": 1}


def test_parse_json_malformado_degrada_a_texto() -> None:
    raw = "Esto no es JSON válido — sólo texto."
    message, structured = parse_llm_output(raw, "json")
    assert message == raw
    assert structured is None


def test_parse_json_top_level_no_dict_degrada_a_texto() -> None:
    message, structured = parse_llm_output('["a", "b"]', "json")
    assert message == '["a", "b"]'
    assert structured is None


def test_parse_json_sin_message_usa_texto_crudo() -> None:
    raw = json.dumps({"otra_key": "valor"})
    message, structured = parse_llm_output(raw, "json")
    assert message == raw
    assert structured == {"otra_key": "valor"}


def test_parse_json_message_no_string_usa_texto_crudo() -> None:
    raw = json.dumps({"message": 123})
    message, structured = parse_llm_output(raw, "json")
    assert message == raw
    assert structured == {"message": 123}


def test_strip_markdown_fences() -> None:
    assert strip_markdown_fences("```json\n{}\n```") == "{}"
    assert strip_markdown_fences("sin fences") == "sin fences"


def test_looks_like_leak_detecta_marcadores_case_insensitive() -> None:
    markers = ["Notas del instructor", "Vías de Respuesta"]
    assert looks_like_leak("Mirá las NOTAS DEL INSTRUCTOR que te pasé.", markers)
    assert looks_like_leak("Te explico las vías de respuesta esperadas.", markers)


def test_looks_like_leak_no_falsea_positivos() -> None:
    markers = ["Notas del instructor"]
    assert not looks_like_leak("¿Qué evidencia respalda tu argumento?", markers)
    assert not looks_like_leak("", markers)


def test_looks_like_leak_sin_marcadores_es_false() -> None:
    assert not looks_like_leak("Notas del instructor", [])
    assert not looks_like_leak("cualquier cosa", [""])
