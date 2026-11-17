#!/usr/bin/env python3
"""Tunnel Excavation AI - Production API Server Entrypoint

Runs the FastAPI application on the configured host and port (default: 0.0.0.0:8000).
Configurable via .env file or environment variables.
"""

import sys
from pathlib import Path
import uvicorn

# Ensure the root project directory is on sys.path
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from backend.app.config import HOST, PORT

if __name__ == "__main__":
    print(f"Starting Tunnel Excavation AI Server on {HOST}:{PORT} ...")
    uvicorn.run(
        "backend.app.main:app",
        host=HOST,
        port=PORT,
        reload=True,
        log_level="info",
        access_log=True,
    )
