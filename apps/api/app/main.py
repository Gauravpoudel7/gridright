import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.auth import AuthError
from app.routers import auth_error_handler, router

app = FastAPI(title="GridRight API", version="0.1.0")

# Browser-facing CORS. Exact origins come from CORS_ALLOWED_ORIGINS
# (comma-separated); Vercel preview deployments get a wildcard-ish pattern via
# CORS_ALLOWED_ORIGIN_REGEX (e.g. "https://gridright-.*\.vercel\.app"). Local
# dev origins are the default so nothing breaks without env config.
_cors_origins = [
    o.strip()
    for o in os.getenv(
        "CORS_ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
    ).split(",")
    if o.strip()
]
_cors_origin_regex = os.getenv("CORS_ALLOWED_ORIGIN_REGEX") or None

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_origin_regex=_cors_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_exception_handler(AuthError, auth_error_handler)
app.include_router(router)


@app.get("/health")
async def health():
    """Lightweight liveness probe — no DB, no external calls. Safe to ping
    every few minutes to keep a free-tier host (Render) from sleeping."""
    return {"status": "ok"}
