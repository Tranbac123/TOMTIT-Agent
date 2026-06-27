from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agent_core.memory.factory import MemoryBackendConfig
from agent_core.runtime.runtime_agent import build_agent_with_memory_backend, build_local_agent
from agent_core.web_api.routes import router
from agent_core.web_api.session_manager import SessionManager


def _build_agent_and_store():
    backend = os.environ.get("TOMTIT_MEMORY_BACKEND", "local")
    if backend == "local":
        return build_local_agent()
    config = MemoryBackendConfig.from_values(
        backend=backend,
        base_url=os.environ.get("TOMTIT_MEMORY_BASE_URL"),
        project_id=os.environ.get("TOMTIT_MEMORY_PROJECT_ID"),
        default_user_id=os.environ.get("TOMTIT_MEMORY_USER_ID"),
        timeout_seconds=float(os.environ.get("TOMTIT_MEMORY_TIMEOUT_SECONDS", "5.0")),
    )
    return build_agent_with_memory_backend(memory_config=config)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    agent, store = _build_agent_and_store()
    app.state.session_manager = SessionManager(agent=agent, store=store)
    yield


def create_app() -> FastAPI:
    application = FastAPI(
        title="TOMTIT-Agent Web API",
        version="dev",
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(router)
    return application


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("agent_core.web_api.app:app", host="0.0.0.0", port=8000, reload=True)
