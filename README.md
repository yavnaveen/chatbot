# Tunnel Excavation AI - Production & Cloudflare Tunnel Guide

An AI-powered offline database-querying assistant for tunnel excavation data, powered by **`qwen2.5-coder:7b`** via Ollama for high-accuracy Text-to-SQL (using dynamic schema injection, no fine-tuning required), backed by an SQLite database with SQLAlchemy 2.0 ORM, a hardened FastAPI REST API server, and a React + TypeScript frontend.

Configured and hardened for public internet exposure using **Cloudflare Tunnel**.

---

## Architecture & Tech Stack

- **Model:** `qwen2.5-coder:7b` (configurable via `OLLAMA_MODEL` in `.env`)
  - **Zero-Shot Text-to-SQL:** Dynamic database schema injection (table names, columns, data types, enums, date format rules)
  - **Deterministic Generation:** `temperature: 0.0` for precise, reproducible query output
  - **Sanitization:** Markdown code fences (e.g., ````sql````) and conversational filler automatically stripped before execution
- **Backend Framework:** FastAPI 0.115+ & Uvicorn (running on `0.0.0.0:8000`)
- **Database:** SQLite (`backend/data/excavation.db`) with SQLAlchemy 2.0 ORM (auto-seeded with 56 excavation records)
- **Public Tunneling:** Cloudflare Quick Tunnel (`*.trycloudflare.com`) via `cloudflared` (with HTTP/2 fallback)
- **Security & Hardening:**
  - **Read-Only Enforcement:** Strict validator blocking any non-SELECT queries (`DROP`, `DELETE`, `UPDATE`, `INSERT`, `ALTER`, `TRUNCATE`, `EXEC`)
  - **API Key Authentication:** Header check (`X-API-Key`) validated against `API_SECRET_KEY` using constant-time comparison
  - **IP Rate Limiting:** Sliding-window rate limiter per client IP (Cloudflare `CF-Connecting-IP` aware)
  - **CORS:** Enabled for external web and mobile clients

---

## Hardware Notes for `qwen2.5-coder:7b`

`qwen2.5-coder:7b` runs locally via Ollama with 4-bit quantization (Q4_K_M):
- **VRAM (GPU):** ~5.5 GB to 8 GB VRAM recommended for fast GPU offloading (e.g., NVIDIA RTX 3060/4060 or Apple Silicon M-series).
- **RAM (CPU-only):** Minimum 12 GB system RAM (16 GB recommended) if running entirely on CPU.
- **Disk Space:** ~4.7 GB for the model weights in Ollama.
- **Model Download:**
  ```powershell
  ollama pull qwen2.5-coder:7b
  ```

---

## Quick Start (Run Locally on Your System)

Simply double-click or run in PowerShell:
```powershell
cd D:\Softwares\chatbot; .\run.bat
```

This single command automatically:
1. Starts the local **Ollama** service in the background.
2. Starts the **FastAPI** backend API server on `http://localhost:8000`.
3. Starts the **React** chat frontend on `http://localhost:5173`.
4. Automatically opens **http://localhost:5173** in your default web browser.


---

## Configuration (`.env`)

```ini
# Server Network Configuration
HOST=0.0.0.0
PORT=8000

# Security: API Key Authentication (Required for public endpoints)
API_SECRET_KEY=3Wl2M691mvWR1TsJteWUav8r_n5No3MutqPmRV89D2U

# Cross-Origin Resource Sharing (CORS)
CORS_ORIGINS=*

# Rate Limiting (Max requests per minute per client IP on /chat)
RATE_LIMIT_PER_MINUTE=60

# Local LLM Service (Ollama)
OLLAMA_URL=http://127.0.0.1:11434
OLLAMA_MODEL=qwen2.5-coder:7b
```

---

## API Endpoints & Usage

### 1. Chat Endpoint (`POST /chat`)
Public endpoint accepting natural language queries, generating the SQL query via `qwen2.5-coder:7b`, executing it safely, and returning the formatted answer along with the generated query.

- **URL:** `https://<your-subdomain>.trycloudflare.com/chat` (or `http://localhost:8000/chat`)
- **Method:** `POST`
- **Headers:**
  - `Content-Type: application/json`
  - `X-API-Key: <YOUR_API_SECRET_KEY>`
- **Payload:**
```json
{
  "message": "What was the actual excavation on 01-01-2025?"
}
```

#### Sample `curl` Request
```bash
curl -X POST "https://your-tunnel-subdomain.trycloudflare.com/chat" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: 3Wl2M691mvWR1TsJteWUav8r_n5No3MutqPmRV89D2U" \
  -d '{"message": "What was the actual excavation on 01-01-2025?"}'
```

#### Sample Response
```json
{
  "response": "On 01-01-2025, pull was 0.5, actual excavation was 5.5 and theoretical excavation was 7.5. Support class was A.",
  "generated_query": "SELECT excavation_records.id, excavation_records.date, excavation_records.start_ch, excavation_records.end_ch, excavation_records.pull, excavation_records.support_class, excavation_records.theoretical_volume, excavation_records.actual_volume \nFROM excavation_records \nWHERE excavation_records.date = '01-01-2025' ORDER BY excavation_records.date",
  "status": "success",
  "conversation_id": 1,
  "table": [
    ["Date", "Pull", "Support Class", "Theoretical", "Actual"],
    ["01-01-2025", "0.5", "A", "7.5", "5.5"]
  ]
}
```

---

### 2. System Health Check (`GET /health`)
Verifies that both the SQLite database connection is active and `qwen2.5-coder:7b` is reachable and loaded in Ollama.

#### Sample `curl` Request
```bash
curl -X GET "https://your-tunnel-subdomain.trycloudflare.com/health"
```

#### Sample Response
```json
{
  "status": "healthy",
  "database": {
    "status": "connected",
    "records": 56,
    "error": null
  },
  "ollama": {
    "status": "connected",
    "model": "qwen2.5-coder:7b",
    "model_available": true,
    "installed_models": ["qwen2.5-coder:7b"],
    "error": null
  }
}
```

---

## Security Audit & Database Hardening Summary

| Protection Layer | Details |
|---|---|
| **Read-Only SQL Enforcement** | Queries must strictly start with `SELECT`; non-read statements (`DROP`, `DELETE`, `UPDATE`, `INSERT`, `ALTER`, `TRUNCATE`, `EXEC`) and multi-statement injection attempts are immediately rejected with a 400 error before execution. |
| **API Key Authentication** | Incoming requests to protected endpoints must supply an `X-API-Key` header matching `API_SECRET_KEY` in `.env` using constant-time `secrets.compare_digest`. Mismatches receive `401 Unauthorized`. |
| **Rate Limiting** | Sliding-window limiter on `/chat` resolving client IP via `CF-Connecting-IP` (Cloudflare) to block denial-of-service attempts. Exceeding the threshold returns `429 Too Many Requests`. |
| **CORS Middleware** | Set to `allow_origins=["*"]` so browser frontends and mobile apps can communicate through Cloudflare Tunnel without cross-origin blocks. |
| **Zero-Shot Prompt Injection** | Dynamic schema injection provides SQLite table definitions, column types, and date format conventions directly in the system prompt with zero fine-tuning required. |

---

## Automated Verification & Tests

To execute the test suite:
```powershell
python -m pytest backend/tests -v
```
All **30 unit and integration tests** verify:
- Zero-shot Text-to-SQL query generation
- Stripping markdown fences (````sql````) and conversational text
- Rejection of destructive statements (`DROP`, `DELETE`, `UPDATE`, etc.)
- API key authentication validation and 401 rejection
- Sliding-window rate limiting (429 rejection)
- System health check probe
- Database integrity and excavation data querying
