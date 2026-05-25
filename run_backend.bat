@echo off
setlocal

REM Run FastAPI backend for Dynamic Pricing Engine
REM Usage: double-click or run from a terminal.

cd /d "%~dp0"

REM Optional: set allowed CORS origins (comma-separated)
REM set "ALLOWED_ORIGINS=http://localhost:5173,https://dynamic-pricing-engine-gamma.vercel.app"

py -m uvicorn api.index:app --reload --host 127.0.0.1 --port 8000

