"""Single public origin: the Chaitanya frontend and the model API in one service."""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from backend.main import app as api


@asynccontextmanager
async def lifespan(application):
    # Mounted ASGI apps do not automatically run their own lifespan handlers.
    async with api.router.lifespan_context(api):
        yield


app = FastAPI(title="NAGARSAATHI", docs_url=None, redoc_url=None, lifespan=lifespan)
app.mount("/api", api)
dist = Path(__file__).resolve().parents[1] / "dist"
if dist.is_dir():
    app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
