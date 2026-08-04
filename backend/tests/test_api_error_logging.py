import json

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from src.models.schemas import sanitize_system_error
from src.observability import install_api_error_logging


@pytest.mark.asyncio
async def test_api_error_is_written_as_safe_json_line(tmp_path):
    app = FastAPI()
    install_api_error_logging(app, log_dir=tmp_path)

    @app.get("/fails")
    async def fails():
        raise HTTPException(status_code=500, detail="internal failure")

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/fails?access_token=do-not-log",
            headers={"Authorization": "Bearer do-not-log"},
        )

    assert response.status_code == 500
    assert response.headers["x-request-id"]

    records = (tmp_path / "api-errors.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(records) == 1
    record = json.loads(records[0])
    assert record["event"] == "api_error"
    assert record["method"] == "GET"
    assert record["path"] == "/fails"
    assert record["status_code"] == 500
    assert record["request_id"] == response.headers["x-request-id"]
    assert "access_token" not in records[0]
    assert "do-not-log" not in records[0]


@pytest.mark.asyncio
async def test_sanitized_system_error_is_written_with_api_context(tmp_path):
    app = FastAPI()
    install_api_error_logging(app, log_dir=tmp_path)

    @app.get("/planner-reply")
    def planner_reply():
        return {
            "reply": sanitize_system_error(
                "SYSTEM ERROR: database password=do-not-log",
                session_id="session-123",
            )
        }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/planner-reply")

    assert response.status_code == 200
    record = json.loads((tmp_path / "api-errors.jsonl").read_text(encoding="utf-8"))
    assert record["event"] == "sanitized_system_error"
    assert record["session_id"] == "session-123"
    assert record["method"] == "GET"
    assert record["path"] == "/planner-reply"
    assert "error_fingerprint" in record
    assert "do-not-log" not in json.dumps(record)
