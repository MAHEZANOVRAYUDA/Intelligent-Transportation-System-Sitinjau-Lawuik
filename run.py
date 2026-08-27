"""Run the Sitinjau Laut monitoring server."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import uvicorn

from src.config import get_settings


def main():
    _, env = get_settings()
    # Reload dimatikan: WatchFiles pada seluruh folder (termasuk venv) membuat halaman pending.
    uvicorn.run(
        "src.api.main:app",
        host=env.api_host,
        port=env.api_port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
