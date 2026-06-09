"""
Launcher uvicorn para el API entrypoint.

Se invoca con `python -m westfield_agent_back_python.main_api` (eso es lo
que llama el Makefile, el Dockerfile y el docker-compose). En dev habilita
reload para que los cambios de código se reflejen sin reiniciar manualmente.
"""

from __future__ import annotations

import os

import uvicorn

from westfield_agent_back_python.shared.config import load_config


def main() -> None:
    cfg = load_config()
    uvicorn.run(
        "westfield_agent_back_python.entrypoints.api:app",
        host=cfg["service"]["host"],
        port=cfg["service"]["port"],
        reload=(os.getenv("ENV", "dev") == "dev"),
    )


if __name__ == "__main__":
    main()
