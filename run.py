"""Run the Sitinjau Laut monitoring server."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import uvicorn

from src.config import get_settings


def main():
    _, env = get_settings()
    # Batasi reload hanya memantau direktori src/ agar tidak memindai venv atau data
    reload_enabled = bool(env.api_debug)
    uvicorn.run(
        "src.api.main:app",
        host=env.api_host,
        port=env.api_port,
        reload=reload_enabled,
        reload_dirs=[str(ROOT / "src")] if reload_enabled else None,
        log_level="info",
    )


if __name__ == "__main__":
    main()
