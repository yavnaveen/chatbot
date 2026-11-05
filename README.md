# Tunnel Excavation AI

Local React + TypeScript + Tailwind frontend with a FastAPI + SQLite + SQLAlchemy backend. The database is seeded automatically from the supplied 56-row excavation dataset in `backend/data/seed_data.py` on first startup.

## Run

Backend (from this folder):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
python -m backend
```

Frontend (another terminal):

```powershell
cd frontend
npm install
npm run dev
```

Start Ollama separately and make sure the model in `OLLAMA_MODEL` is installed. The default is `qwen3:4b-instruct-2507-q4_K_M`.
