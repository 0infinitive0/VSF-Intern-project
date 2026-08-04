import json

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

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
