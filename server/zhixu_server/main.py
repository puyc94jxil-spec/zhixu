"""应用入口。启动时初始化数据库、恢复中断任务，并记录隔离探针，不探测模型内网。"""

from __future__ import annotations

import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from zhixu_server.api import mount_pages, router
from zhixu_server.config import Settings, load_settings
from zhixu_server.db import init_db
from zhixu_server.logutil import get_logger, log_event
from zhixu_server.sandbox import probe
from zhixu_server.service import recover_jobs


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    get_logger(settings.log_path)
    init_db(settings)
    recovered = recover_jobs(settings)
    purged = {"removed": 0}
    if settings.backup_dir is not None:
        from zhixu_server.backup import purge_expired_backups

        try:
            purged = purge_expired_backups(settings.backup_dir, settings.backup_retention_days)
        except RuntimeError:
            purged = {"removed": 0, "error": "refuse_purge_data_dir"}
    isolation = probe()
    log_event(
        "boot",
        upstream_mode=settings.upstream_mode,
        model_configured=bool(settings.model_base_url and settings.model_name),
        isolation_ready=bool(isolation.get("ready")),
        recovered=recovered,
        backup_purged=purged.get("removed", 0),
    )
    app = FastAPI(title="知序", version="0.2.0-phase-b")
    app.state.settings = settings

    @app.middleware("http")
    async def request_id(request: Request, call_next):
        request.state.request_id = uuid.uuid4().hex
        try:
            response = await call_next(request)
        except Exception:
            log_event(
                "unhandled",
                error_code="internal",
                path=request.url.path,
                exc_type="internal",
            )
            return JSONResponse(
                status_code=500,
                content={
                    "error": {
                        "code": "internal",
                        "message": "内部错误",
                        "request_id": request.state.request_id,
                    }
                },
            )
        response.headers["X-Request-Id"] = request.state.request_id
        return response

    app.include_router(router)
    mount_pages(app, settings)
    return app


def main() -> None:
    import uvicorn

    settings = load_settings()
    uvicorn.run(
        "zhixu_server.main:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
    )


if __name__ == "__main__":
    main()
