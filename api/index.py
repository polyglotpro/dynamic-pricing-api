import os

from fastapi.middleware.cors import CORSMiddleware

# Reuse the existing FastAPI app (keeps all business routes unchanged).
from app.main import app  # noqa: E402


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # temporary for testing
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
