import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from time import perf_counter
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from growth_agent import __version__
from growth_agent.config import Settings
from growth_agent.data.generator import generate_data
from growth_agent.logging_config import configure_logging
from growth_agent.models import AnalysisReport, AnalysisRequest
from growth_agent.service.jobs import IdempotencyConflictError, JobManager, QueueFullError
from growth_agent.service.lab import router as lab_router
from growth_agent.service.pipeline import GrowthPipeline
from growth_agent.storage import JobStore, public_job

logger = logging.getLogger("growth_agent.api")
IdempotencyKey = Annotated[str | None, Header(max_length=128, pattern=r"^[a-zA-Z0-9_-]+$")]


class BodyLimitMiddleware:
    """Limit streamed bodies before parsing JSON, even without Content-Length."""

    def __init__(self, app, max_bytes: int = 4 * 1024 * 1024):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        chunks = []
        total = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            total += len(chunk)
            if total > self.max_bytes:
                response = JSONResponse(
                    status_code=413,
                    content={
                        "error": {
                            "code": "payload_too_large",
                            "message": "Request exceeds 4 MiB",
                            "request_id": scope["state"]["request_id"],
                        }
                    },
                )
                return await response(scope, receive, send)
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        consumed = False

        async def replay():
            nonlocal consumed
            if not consumed:
                consumed = True
                return {"type": "http.request", "body": b"".join(chunks), "more_body": False}
            return await receive()

        return await self.app(scope, replay, send)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configure_logging(settings.log_level)
        store = JobStore(settings.database_path)
        manager = JobManager(
            store, GrowthPipeline(settings), settings.job_workers, settings.max_pending_jobs
        )
        app.state.store = store
        app.state.jobs = manager
        app.state.pipeline = manager.pipeline
        yield
        manager.close()

    app = FastAPI(title="Growth Decision Agent", version=__version__, lifespan=lifespan)
    app.add_middleware(BodyLimitMiddleware)
    app.include_router(lab_router)

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request.state.request_id = str(uuid4())
        start = perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:
            logger.error(
                "request_failed",
                extra={"request_id": request.state.request_id, "error_type": type(exc).__name__},
            )
            response = error(request, 500, "internal_error", "Unexpected server error")
        response.headers["X-Request-ID"] = request.state.request_id
        logger.info(
            "request_complete",
            extra={
                "request_id": request.state.request_id,
                "status_code": response.status_code,
                "duration_ms": round((perf_counter() - start) * 1000, 3),
            },
        )
        return response

    def error(request, status, code, message, details=None, headers=None):
        return JSONResponse(
            status_code=status,
            headers=headers,
            content={
                "error": {
                    "code": code,
                    "message": message,
                    "request_id": request.state.request_id,
                    "details": details or [],
                }
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        details = [{"location": list(e["loc"]), "type": e["type"]} for e in exc.errors()]
        return error(
            request, 422, "validation_error", "Invalid request; check schema in /docs", details
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request, exc):
        return error(request, exc.status_code, "http_error", str(exc.detail), headers=exc.headers)

    @app.exception_handler(QueueFullError)
    async def queue_error(request, exc):
        return error(
            request,
            429,
            "queue_full",
            "Retry after a pending job completes",
            headers={"Retry-After": "2"},
        )

    @app.exception_handler(IdempotencyConflictError)
    async def conflict_error(request, exc):
        return error(request, 409, "idempotency_conflict", "Key was used with different input")

    @app.get("/", include_in_schema=False)
    def dashboard():
        return FileResponse(Path(__file__).parent / "static" / "index.html")

    @app.get("/v1/examples")
    def examples():
        return {"data_kind": "synthetic", "analysis": generate_data()[0]}

    @app.get("/health")
    def health():
        return {"status": "ok", "version": __version__}

    @app.get("/ready")
    def ready(request: Request):
        if not request.app.state.store.ping():
            raise HTTPException(503, "Storage unavailable")
        return {"status": "ready"}

    @app.post("/v1/analyze", response_model=AnalysisReport)
    def analyze(payload: AnalysisRequest, request: Request):
        return request.app.state.pipeline.run(payload, run_id=request.state.request_id)

    @app.post("/v1/jobs", status_code=202)
    def submit(payload: AnalysisRequest, request: Request, idempotency_key: IdempotencyKey = None):
        job_id = request.app.state.jobs.submit(payload, key=idempotency_key)
        return {
            "job_id": job_id,
            "status_url": f"/v1/jobs/{job_id}",
            "report_url": f"/v1/jobs/{job_id}/report",
        }

    @app.get("/v1/jobs")
    def list_jobs(request: Request, limit: Annotated[int, Query(ge=1, le=100)] = 20):
        return {"jobs": request.app.state.store.list_recent(limit)}

    def get_job(request: Request, job_id: UUID):
        row = request.app.state.store.get(str(job_id))
        if not row:
            raise HTTPException(404, "Job not found")
        return row

    @app.get("/v1/jobs/{job_id}")
    def job_status(job_id: UUID, request: Request):
        return public_job(get_job(request, job_id))

    @app.get("/v1/jobs/{job_id}/report", response_model=AnalysisReport)
    def job_report(job_id: UUID, request: Request):
        row = get_job(request, job_id)
        if row["status"] != "succeeded":
            raise HTTPException(409, f"Report unavailable: job is {row['status']}")
        return json.loads(row["report_json"])

    @app.post("/v1/jobs/{job_id}/replay", status_code=202)
    def replay_job(job_id: UUID, request: Request, idempotency_key: IdempotencyKey = None):
        row = get_job(request, job_id)
        payload = AnalysisRequest.model_validate_json(row["request_json"])
        replay_id = request.app.state.jobs.submit(payload, key=idempotency_key, source=str(job_id))
        return {
            "job_id": replay_id,
            "source_job_id": str(job_id),
            "status_url": f"/v1/jobs/{replay_id}",
        }

    return app


app = create_app()
