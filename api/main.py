"""FastAPI application entry point (Phase 0 skeleton).

Run with (see scripts/start-pipeline-api.bat):

    uvicorn api.main:app --host 127.0.0.1 --port 8000 --workers 1

``--workers 1`` is mandatory — see docs §4.4/§11: the GPU job queue is an
in-process singleton and multiple worker processes would each get their own
queue, breaking single-GPU serialization.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routers import artifacts, batch, filesystem, media, params, pipeline, projects, slices, stages


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    params.warm_schema_cache()
    yield


app = FastAPI(title="voice-translate pipeline API", version="0.1.0", lifespan=_lifespan)

# Vite dev server default ports; adjust/extend once frontend/vite.config.ts lands in Phase 1.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(projects.router)
app.include_router(params.router)
app.include_router(media.router)
app.include_router(stages.router)
app.include_router(slices.router)
app.include_router(artifacts.router)
app.include_router(filesystem.router)
app.include_router(batch.router)
app.include_router(pipeline.router)


@app.get("/api/health")
@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
