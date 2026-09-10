from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from growth_agent.api import create_app
from growth_agent.config import Settings
from growth_agent.models import AnalysisRequest


@pytest.fixture
def payload():
    start = date(2025, 1, 6)
    rows = [
        {
            "date": (start + timedelta(days=i)).isoformat(),
            "channel": "ads",
            "visitors": 10000,
            "new_users": 1000,
            "spend": 2000,
        }
        for i in range(64)
    ]
    rows[-1].update(visitors=4000, new_users=400)
    return {"records": rows}


@pytest.fixture
def analysis_request(payload):
    return AnalysisRequest.model_validate(payload)


@pytest.fixture
def settings(tmp_path):
    return Settings(
        _env_file=None,
        database_path=str(tmp_path / "jobs.sqlite3"),
        llm_enabled=False,
        log_level="ERROR",
    )


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as test_client:
        yield test_client
