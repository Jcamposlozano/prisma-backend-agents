"""
Logger único del servicio. Mismo handler para todos los módulos para evitar
duplicación si se importa logging desde varios lugares.

Compatible con el template ESIC.
"""

from __future__ import annotations

import logging
import os


def get_logger(name: str = "app") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    logger.setLevel(level)
    handler = logging.StreamHandler()
    formatter = logging.Formatter("[%(levelname)s] %(asctime)s - %(name)s: %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger
