from pathlib import Path
import os
from dotenv import load_dotenv

# Locate root directory containing .env
BASE_DIR = Path(__file__).resolve().parents[2]
ENV_FILE = BASE_DIR / ".env"

if ENV_FILE.exists():
    load_dotenv(ENV_FILE)
else:
    load_dotenv()

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
API_SECRET_KEY = os.getenv("API_SECRET_KEY", "")
CORS_ORIGINS_RAW = os.getenv("CORS_ORIGINS", "*")
if CORS_ORIGINS_RAW == "*":
    CORS_ORIGINS = ["*"]
else:
    CORS_ORIGINS = [item.strip() for item in CORS_ORIGINS_RAW.split(",") if item.strip()]

RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", "60"))
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5-coder:7b")
