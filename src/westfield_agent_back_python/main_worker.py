"""
Launcher del Worker entrypoint.

Se invoca con `python -m westfield_agent_back_python.main_worker`.
"""

from __future__ import annotations

from westfield_agent_back_python.entrypoints.worker import main

if __name__ == "__main__":
    main()
