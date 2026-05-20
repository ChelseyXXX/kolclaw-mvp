from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import router
from app.storage.database import get_connection, init_db


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    with get_connection() as conn:
        init_db(conn)
    yield


app = FastAPI(
    title="KOLClaw Creator Analysis MVP",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(router)
