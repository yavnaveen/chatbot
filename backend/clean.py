#!/usr/bin/env python3
"""Cleanup utility for Tunnel Excavation AI:
- Removes Python __pycache__ bytecode directories and .pyc files
- Removes .pytest_cache and Vite dev caches
- Clears previous chat conversation history and messages from database
- Preserves all core excavation data records
"""

import shutil
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy import text
from backend.app.db import get_session

def clean_caches():
    pycache_count = 0
    for p in ROOT_DIR.rglob("__pycache__"):
        try:
            shutil.rmtree(p, ignore_errors=True)
            pycache_count += 1
        except Exception:
            pass

    for ext in ("*.pyc", "*.pyo"):
        for p in ROOT_DIR.rglob(ext):
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass

    for folder_name in (".pytest_cache", "frontend/node_modules/.vite", "frontend/dist"):
        folder = ROOT_DIR / folder_name
        if folder.exists():
            shutil.rmtree(folder, ignore_errors=True)

    print(f"      [OK] Cleaned {pycache_count} __pycache__ folders and build caches.")

def clean_conversation_memory():
    try:
        with get_session() as session:
            session.execute(text("DELETE FROM messages"))
            session.execute(text("DELETE FROM conversations"))
            session.commit()
            record_count = session.execute(text("SELECT count(*) FROM excavation_records")).scalar() or 0
        print(f"      [OK] Cleared previous conversation memory (preserved {record_count} excavation records).")
    except Exception as exc:
        print(f"      [!] Warning: Could not clear conversation memory: {exc}")

if __name__ == "__main__":
    clean_caches()
    clean_conversation_memory()
