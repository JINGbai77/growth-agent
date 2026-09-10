import json
from threading import Event

import pytest

from growth_agent.service.jobs import JobManager, QueueFullError
from growth_agent.service.pipeline import GrowthPipeline
from growth_agent.storage import JobStore, request_hash


def test_restart_marks_inflight_and_preserves_completed(tmp_path, analysis_request, settings):
    path = str(tmp_path / "db.sqlite3")
    store = JobStore(path)
    queued = store.create(analysis_request, None, None)
    running = store.create(analysis_request, None, None)
    store.start(running)
    finished = store.create(analysis_request, None, None)
    store.finish(finished, GrowthPipeline(settings).run(analysis_request, run_id=finished))
    reopened = JobStore(path)
    assert reopened.recover_interrupted() == 2
    assert reopened.get(queued)["status"] == reopened.get(running)["status"] == "interrupted"
    assert reopened.get(finished)["status"] == "succeeded"
    assert json.loads(reopened.get(finished)["report_json"])["run_id"] == finished
    assert reopened.recover_interrupted() == 0


def test_bounded_queue_and_capacity_release(tmp_path, settings, analysis_request):
    entered, release = Event(), Event()
    pipeline = GrowthPipeline(settings)
    original = pipeline.run

    def block(request, run_id):
        entered.set()
        assert release.wait(5)
        return original(request, run_id)

    pipeline.run = block
    manager = JobManager(JobStore(str(tmp_path / "db.sqlite3")), pipeline, workers=1, capacity=1)
    try:
        first = manager.submit(analysis_request, key="one")
        assert entered.wait(5)
        assert manager.submit(analysis_request, key="one") == first
        with pytest.raises(QueueFullError):
            manager.submit(analysis_request)
    finally:
        release.set()
        manager.close()
    assert manager.store.get(first)["status"] == "succeeded"
    assert manager.capacity.acquire(blocking=False)
    manager.capacity.release()
    with pytest.raises(QueueFullError):
        manager.submit(analysis_request)


def test_dispatch_failure_releases_capacity(tmp_path, settings, analysis_request, monkeypatch):
    manager = JobManager(
        JobStore(str(tmp_path / "db.sqlite3")), GrowthPipeline(settings), workers=1, capacity=1
    )

    def broken(*args, **kwargs):
        raise RuntimeError("dispatch failure")

    monkeypatch.setattr(manager.pool, "submit", broken)
    with pytest.raises(RuntimeError):
        manager.submit(analysis_request)
    assert manager.capacity.acquire(blocking=False)
    manager.capacity.release()
    assert manager.store.list_recent()[0]["error_code"] == "dispatch_failed"
    manager.close()


def test_hash_ignores_order_but_tracks_options(analysis_request):
    reordered = analysis_request.model_copy(
        update={"records": list(reversed(analysis_request.records))}
    )
    assert request_hash(analysis_request) == request_hash(reordered)
    changed = analysis_request.model_copy(update={"use_llm": True})
    assert request_hash(analysis_request) != request_hash(changed)
