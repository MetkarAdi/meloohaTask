import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.chart.router import router as chart_router
from app.db.router import router as db_router
from app.db.admin import router as admin_router
from app.db.insights import router as insights_router
from app.locations.router import router as locations_router
from app.speech.router import router as speech_router
from app.db.session import configured_database_url, run_migrations, shutdown_database, verify_database_connection

PROJECT_ROOT = Path(__file__).resolve().parents[1]
# .env.local is written by the Neon CLI and should override a general .env file.
# Tests set a dedicated database URL and skip filesystem env files entirely.
if os.getenv("MELOOHA_SKIP_DOTENV") != "1":
    load_dotenv(PROJECT_ROOT / ".env.local")
    load_dotenv(PROJECT_ROOT / ".env")


@asynccontextmanager
async def lifespan(_: FastAPI):
    if configured_database_url():
        verify_database_connection()
        run_migrations()
    yield
    shutdown_database()

app = FastAPI(title="Melooha API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(chart_router)
app.include_router(db_router)
app.include_router(insights_router)
app.include_router(admin_router)
app.include_router(locations_router)
app.include_router(speech_router)


@app.get("/health")
def health():
    llm_configured = any(
        os.getenv(name, "").strip()
        for name in (
            "GROQ_API_KEY", "GROQ_API_KEY_2", "GROQ_API_KEY_3", "GROQ_API_KEY_4",
            "GEMINI_API_KEY",
        )
    )
    return {"status": "ok", "llm_configured": llm_configured}
