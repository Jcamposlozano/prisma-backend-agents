"""Tests de la carga de configuración (prefijo S3 multi-tenant)."""

from __future__ import annotations

from pathlib import Path

from westfield_agent_back_python.shared.config import load_config

BASE_YAML = """
project:
  name: test
s3:
  bucket: test-bucket
  prefix: org={university_code}/agents
"""


def _write_configs(tmp_path: Path, base: str = BASE_YAML) -> str:
    (tmp_path / "base.yaml").write_text(base, encoding="utf-8")
    return str(tmp_path)


def test_prefix_template_se_preserva_para_resolver_por_request(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("S3_PREFIX", raising=False)

    cfg = load_config(_write_configs(tmp_path))
    # El placeholder NO se sustituye al cargar — lo resuelve el registry
    # por request con el segmento de la ruta.
    assert cfg["s3"]["prefix"] == "org={university_code}/agents"


def test_s3_prefix_por_env_pisa_el_yaml(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("S3_PREFIX", "layout/custom")

    cfg = load_config(_write_configs(tmp_path))
    assert cfg["s3"]["prefix"] == "layout/custom"


def test_prefix_default_es_la_convencion_multitenant(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("S3_PREFIX", raising=False)

    base = BASE_YAML.replace("  prefix: org={university_code}/agents\n", "")
    cfg = load_config(_write_configs(tmp_path, base))
    assert cfg["s3"]["prefix"] == "org={university_code}/agents"
