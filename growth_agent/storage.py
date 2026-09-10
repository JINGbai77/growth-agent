import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from growth_agent import __version__
from growth_agent.models import AnalysisReport, AnalysisRequest


def now() -> str:
    return datetime.now(UTC).isoformat()


def request_hash(request: AnalysisRequest) -> str:
    payload = request.model_dump(mode="json")
    payload["records"].sort(key=lambda r: (r["date"], r["channel"]))
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


class JobStore:
    """Per-operation connections; no shared SQLite connection across worker threads."""

    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as conn, conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, status TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    request_json TEXT NOT NULL, request_hash TEXT NOT NULL,
                    report_json TEXT, error_code TEXT,
                    idempotency_key TEXT UNIQUE, source_job_id TEXT,
                    engine_version TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS artifacts (
                    id TEXT PRIMARY KEY, source_job_id TEXT NOT NULL,
                    kind TEXT NOT NULL, created_at TEXT NOT NULL,
                    input_json TEXT NOT NULL, result_json TEXT NOT NULL,
                    engine_version TEXT NOT NULL,
                    FOREIGN KEY(source_job_id) REFERENCES jobs(id)
                )
            """)

    def save_artifact(self, job_id: str, kind: str, input_json: str, result_json: str) -> str:
        artifact_id = str(uuid4())
        with closing(self.connect()) as conn, conn:
            conn.execute(
                "INSERT INTO artifacts VALUES (?, ?, ?, ?, ?, ?, ?)",
                (artifact_id, job_id, kind, now(), input_json, result_json, __version__),
            )
        return artifact_id

    def list_artifacts(self, job_id: str):
        with closing(self.connect()) as conn:
            rows = conn.execute(
                "SELECT id,source_job_id,kind,created_at,result_json,engine_version "
                "FROM artifacts WHERE source_job_id=? ORDER BY created_at",
                (job_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def connect(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def create(self, request: AnalysisRequest, key: str | None, source: str | None) -> str:
        job_id = str(uuid4())
        stamp = now()
        with closing(self.connect()) as conn, conn:
            conn.execute(
                "INSERT INTO jobs VALUES (?, 'queued', ?, ?, ?, ?, NULL, NULL, ?, ?, ?)",
                (
                    job_id,
                    stamp,
                    stamp,
                    request.model_dump_json(),
                    request_hash(request),
                    key,
                    source,
                    __version__,
                ),
            )
        return job_id

    def by_key(self, key: str):
        with closing(self.connect()) as conn:
            row = conn.execute("SELECT * FROM jobs WHERE idempotency_key = ?", (key,)).fetchone()
        return dict(row) if row else None

    def get(self, job_id: str):
        with closing(self.connect()) as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None

    def list_recent(self, limit: int = 20):
        with closing(self.connect()) as conn:
            rows = conn.execute(
                "SELECT id,status,created_at,updated_at,error_code,source_job_id,engine_version "
                "FROM jobs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def start(self, job_id: str) -> None:
        with closing(self.connect()) as conn, conn:
            conn.execute(
                "UPDATE jobs SET status='running', updated_at=? WHERE id=?", (now(), job_id)
            )

    def finish(self, job_id: str, report: AnalysisReport) -> None:
        with closing(self.connect()) as conn, conn:
            conn.execute(
                "UPDATE jobs SET status='succeeded', updated_at=?, report_json=? WHERE id=?",
                (now(), report.model_dump_json(), job_id),
            )

    def fail(self, job_id: str, code: str = "pipeline_failed") -> None:
        with closing(self.connect()) as conn, conn:
            conn.execute(
                "UPDATE jobs SET status='failed', updated_at=?, error_code=? WHERE id=?",
                (now(), code, job_id),
            )

    def recover_interrupted(self) -> int:
        # Only one API process may own a database. Never silently re-run model calls.
        with closing(self.connect()) as conn, conn:
            cursor = conn.execute(
                "UPDATE jobs SET status='interrupted', updated_at=?, error_code='server_restarted' "
                "WHERE status IN ('queued','running')",
                (now(),),
            )
            return cursor.rowcount

    def ping(self) -> bool:
        with closing(self.connect()) as conn:
            return conn.execute("SELECT 1").fetchone()[0] == 1


def public_job(row: dict) -> dict:
    return {
        key: value
        for key, value in row.items()
        if key not in {"request_json", "request_hash", "report_json", "idempotency_key"}
    }
