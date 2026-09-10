import logging
from concurrent.futures import ThreadPoolExecutor
from threading import BoundedSemaphore, Lock

from growth_agent.lease import ProcessLease
from growth_agent.models import AnalysisRequest
from growth_agent.service.pipeline import GrowthPipeline
from growth_agent.storage import JobStore, request_hash

logger = logging.getLogger("growth_agent.jobs")


class QueueFullError(Exception):
    pass


class IdempotencyConflictError(Exception):
    pass


class JobManager:
    """Single-process bounded executor with persisted inputs, states and reports."""

    def __init__(self, store: JobStore, pipeline: GrowthPipeline, workers: int, capacity: int):
        self.store = store
        self.pipeline = pipeline
        self.lease = ProcessLease(store.path)
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="growth")
        self.capacity = BoundedSemaphore(capacity)
        self.lock = Lock()
        self.closed = False
        self.store.recover_interrupted()

    def submit(
        self, request: AnalysisRequest, key: str | None = None, source: str | None = None
    ) -> str:
        with self.lock:
            if self.closed:
                raise QueueFullError()
            if key:
                existing = self.store.by_key(key)
                if existing:
                    if existing["request_hash"] != request_hash(request):
                        raise IdempotencyConflictError()
                    return existing["id"]
            if not self.capacity.acquire(blocking=False):
                raise QueueFullError()
            job_id = None
            try:
                job_id = self.store.create(request, key, source)
                self.pool.submit(self._execute, job_id, request)
            except Exception:
                self.capacity.release()
                if job_id:
                    self.store.fail(job_id, "dispatch_failed")
                raise
            return job_id

    def _execute(self, job_id: str, request: AnalysisRequest) -> None:
        try:
            self.store.start(job_id)
            report = self.pipeline.run(request, run_id=job_id)
            self.store.finish(job_id, report)
        except Exception as exc:
            logger.error("job_failed", extra={"run_id": job_id, "error_type": type(exc).__name__})
            try:
                self.store.fail(job_id)
            except Exception as storage_exc:
                logger.error(
                    "job_state_write_failed",
                    extra={"run_id": job_id, "error_type": type(storage_exc).__name__},
                )
        finally:
            self.capacity.release()

    def close(self):
        with self.lock:
            self.closed = True
        try:
            self.pool.shutdown(wait=True)
        finally:
            self.lease.close()
