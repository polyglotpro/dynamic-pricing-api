import os

from fastapi.middleware.cors import CORSMiddleware
from app.main import app


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://dynamic-pricing-frontend-seven.vercel.app",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {
        "service": "dynamic-pricing-api",
        "status": "ok"
    }


@app.get("/health")
def health():
    return {"ok": True}