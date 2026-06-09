"""
Worker entrypoint — V1: stub no-op.

La plantilla ESIC incluye un Worker como segundo entrypoint del servicio
(además de la API). En V1 del agente Maia no hay tareas background reales,
así que el tick() es no-op y sólo loggea heartbeats.

Si en el futuro hace falta trabajo background (ej. re-embedding periódico
de docs, recolección de analítica, refresh de manifest desde Drive), va acá.
"""

from __future__ import annotations

import time

from westfield_agent_back_python.shared.config import load_config
from westfield_agent_back_python.shared.logger import get_logger
from westfield_agent_back_python.shared.shutdown import ShutdownSignal

log = get_logger("westfield_agent_back_python.worker")


def tick() -> None:
    """Sin trabajo definido por ahora. Sólo confirma que el worker está vivo."""
    log.info("Worker tick (V1: no-op)")


def main() -> None:
    cfg = load_config()
    if not cfg["worker"]["enabled"]:
        log.info("Worker deshabilitado por config — saliendo.")
        return

    interval = cfg["worker"]["interval_seconds"]
    shutdown = ShutdownSignal()
    log.info(f"Worker iniciado. interval_seconds={interval}")

    while not shutdown.is_set():
        start = time.time()
        try:
            tick()
        except Exception:
            log.exception("Error en tick")
        elapsed = time.time() - start
        shutdown.wait(timeout=max(0.0, interval - elapsed))

    log.info("Worker detenido (shutdown).")


if __name__ == "__main__":
    main()
