import os

# Reuse the existing FastAPI app (keeps all business routes unchanged).
from app.main import app  # noqa: E402


@app.get("/")
def root():
    return {"service": "dynamic-pricing-api", "status": "ok"}


@app.get("/health")
def health():
    return {"ok": True}


def _note_cors_config():
    # Helps verify config via logs when deployed (optional; harmless locally).
    allowed = os.getenv("ALLOWED_ORIGINS", "")
    if allowed:
        print(f"[dynamic-pricing-api] ALLOWED_ORIGINS={allowed}")


_note_cors_config()
