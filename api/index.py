import os

# Reuse the existing FastAPI app (keeps all business routes unchanged).
# NOTE: CORS is configured in `app/main.py`. We intentionally do NOT re-add a
# second CORSMiddleware here because it can produce invalid CORS headers
# (especially when `allow_credentials=True`) and cause browsers to surface a
# generic "Failed to fetch" error.
from app.main import app  # noqa: E402


@app.get("/")
def root():
    return {"service": "dynamic-pricing-api", "status": "ok"}


@app.get("/health")
def health():
    return {"ok": True}


def _note_cors_config():
    allowed = os.getenv("ALLOWED_ORIGINS", "")
    if allowed:
        print(f"[dynamic-pricing-api] ALLOWED_ORIGINS={allowed}")


_note_cors_config()
