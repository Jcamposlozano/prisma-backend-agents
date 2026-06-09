"""
Carga de configuración: base.yaml + <env>.yaml + override por env vars.

Extiende el patrón del template ESIC con sección específica de Maia
(`maia.index_path`, `maia.openai.*`) y `rate_limit`.

Las env vars siempre ganan sobre el YAML. Eso permite:
  - dev local: editar configs/dev.yaml
  - prod: setear OPENAI_API_KEY, PORT, etc. desde el orchestrator
  - .env (vía python-dotenv): conveniencia local
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

# Carga .env si existe en el cwd (no falla si no está).
load_dotenv()


def _deep_merge(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """Merge profundo: las keys de `b` sobreescriben a las de `a`."""
    out = dict(a)
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _env_bool(key: str, default: bool) -> bool:
    v = os.getenv(key)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "y", "on"}


def load_config(config_dir: str = "configs") -> dict[str, Any]:
    """
    Lee base.yaml + <ENV>.yaml (si existe) y aplica overrides por env vars.

    Devuelve un dict simple — los entrypoints leen las keys directo. No usamos
    Pydantic Settings acá porque el template ESIC es YAML-first y queremos
    mantener paridad de estructura entre servicios.
    """
    env = os.getenv("ENV", "dev").lower()
    base_path = Path(config_dir) / "base.yaml"
    env_path = Path(config_dir) / f"{env}.yaml"

    with base_path.open("r", encoding="utf-8") as f:
        cfg: dict[str, Any] = yaml.safe_load(f) or {}

    if env_path.exists():
        with env_path.open("r", encoding="utf-8") as f:
            env_cfg: dict[str, Any] = yaml.safe_load(f) or {}
        cfg = _deep_merge(cfg, env_cfg)

    # Garantizar las secciones por si el YAML viene incompleto.
    cfg.setdefault("project", {})
    cfg.setdefault("service", {})
    cfg.setdefault("worker", {})
    cfg.setdefault("maia", {})
    cfg["maia"].setdefault("openai", {})
    cfg.setdefault("rate_limit", {})

    # ---- project ----
    cfg["project"]["env"] = os.getenv("ENV", cfg["project"].get("env", "dev"))
    cfg["project"]["log_level"] = os.getenv(
        "LOG_LEVEL", cfg["project"].get("log_level", "INFO")
    )

    # ---- service ----
    cfg["service"]["host"] = os.getenv("HOST", cfg["service"].get("host", "0.0.0.0"))
    cfg["service"]["port"] = int(os.getenv("PORT", cfg["service"].get("port", 8000)))
    cfg["service"].setdefault("cors_origins", ["http://localhost:5173"])

    # ---- worker ----
    cfg["worker"]["enabled"] = _env_bool(
        "WORKER_ENABLED", bool(cfg["worker"].get("enabled", True))
    )
    cfg["worker"]["interval_seconds"] = int(
        os.getenv("WORKER_INTERVAL_SECONDS", cfg["worker"].get("interval_seconds", 10))
    )

    # ---- maia (RAG + OpenAI) ----
    cfg["maia"]["index_path"] = os.getenv(
        "MAIA_INDEX_PATH", cfg["maia"].get("index_path", "./data/maia-index.json")
    )
    openai_cfg = cfg["maia"]["openai"]
    openai_cfg["api_key"] = os.getenv("OPENAI_API_KEY")  # sin default — None = fallback
    openai_cfg["model"] = os.getenv(
        "OPENAI_MODEL", openai_cfg.get("model", "gpt-4o-mini")
    )
    openai_cfg["embedding_model"] = os.getenv(
        "OPENAI_EMBEDDING_MODEL",
        openai_cfg.get("embedding_model", "text-embedding-3-small"),
    )
    openai_cfg["base_url"] = os.getenv(
        "OPENAI_BASE_URL", openai_cfg.get("base_url", "https://api.openai.com/v1")
    )

    # ---- rate_limit ----
    cfg["rate_limit"]["window_seconds"] = int(
        os.getenv("RATE_LIMIT_WINDOW", cfg["rate_limit"].get("window_seconds", 60))
    )
    cfg["rate_limit"]["max_requests"] = int(
        os.getenv("RATE_LIMIT_MAX", cfg["rate_limit"].get("max_requests", 12))
    )

    return cfg
