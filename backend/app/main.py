"""FastAPI application factory: same-origin local API plus the built frontend."""
from __future__ import annotations

import secrets
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from .api import ai, assets, jobs, presets, reference_data, runs, settings, stacks
from .config import Config, ensure_dirs, load_config
from .db import Database
from .processing.recipe import PIPELINE_VERSION, RECIPE_SCHEMA_VERSION
from .processing.stacking.stack import STACK_VERSION
from .security import SecurityMiddleware
from .services.ai_models import ModelManager
from .services.queue import Coordinator
from .services.reference_data import ReferenceDataManager


def create_app(cfg: Config | None = None, start_worker: bool = True) -> FastAPI:
    cfg = cfg or load_config()
    token = secrets.token_urlsafe(32)  # ephemeral: regenerated on every start, never logged

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        ensure_dirs(cfg)
        db = Database(cfg.db_path)
        presets.seed_builtin_presets(db)
        coordinator = Coordinator(cfg, db)
        app.state.cfg, app.state.db, app.state.coordinator = cfg, db, coordinator
        app.state.ai_models = ModelManager(cfg.ai_models_dir, cfg.min_free_bytes)
        app.state.reference_data = ReferenceDataManager(cfg.reference_data_dir, cfg.min_free_bytes)
        if start_worker:
            coordinator.start()
        yield
        coordinator.stop()
        db.close()

    app = FastAPI(title="EasyAstroEnhance", version=PIPELINE_VERSION, lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url="/api/v1/openapi.json")
    app.state.cfg = cfg

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        detail = exc.detail
        if isinstance(detail, dict) and "code" in detail:
            return JSONResponse({"error": detail}, status_code=exc.status_code)
        return JSONResponse({"error": {"code": "HTTP_ERROR", "message": str(detail)}}, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        return JSONResponse(
            {"error": {"code": "INVALID_REQUEST", "message": "Some values were not accepted; check the highlighted settings.", "detail": [
                {"field": ".".join(str(p) for p in e["loc"][1:]), "problem": e["msg"]} for e in exc.errors()]}},
            status_code=422,
        )

    prefix = "/api/v1"
    for r in (ai.router, assets.router, jobs.router, presets.router, reference_data.router, runs.router, settings.router, stacks.router):
        app.include_router(r, prefix=prefix)

    @app.get(f"{prefix}/session")
    async def session() -> dict[str, Any]:
        return {"token": token, "version": PIPELINE_VERSION, "recipe_schema": RECIPE_SCHEMA_VERSION, "stack_version": STACK_VERSION, "limits": {"max_files": cfg.max_files, "max_file_mib": cfg.max_file_bytes // (1024 * 1024), "max_megapixels": cfg.max_pixels // 1_000_000}}

    @app.get(f"{prefix}/health")
    async def health() -> dict[str, Any]:
        return {"ok": True, "version": PIPELINE_VERSION}

    if cfg.frontend_dist and (cfg.frontend_dist / "index.html").exists():
        app.mount("/", StaticFiles(directory=cfg.frontend_dist, html=True), name="frontend")
    else:
        @app.get("/")
        async def no_frontend():
            return JSONResponse({"message": "Frontend is not built. Run scripts\\setup.ps1 (or use the Vite dev server)."})

    app.add_middleware(SecurityMiddleware, cfg=cfg, token=token)
    return app


app = create_app()
