"""Smoke tests covering the public request lifecycle without real AWS.

S3/DynamoDB calls are monkeypatched so the suite runs offline (e.g. in CI).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.schemas import AnalysisResult, AnalysisStatus
from app.services import database, storage

client = TestClient(app)


def _auth_headers() -> dict[str, str]:
    resp = client.post(
        "/api/v1/auth/dev-login",
        json={"email": "tester@facebyyou.ai", "user_id": "user-123"},
    )
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_health() -> None:
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_requires_auth() -> None:
    assert client.post("/api/v1/uploads/presign", json={}).status_code == 401


def test_get_me(monkeypatch: pytest.MonkeyPatch) -> None:
    # New user: get_user returns None, route falls back to token claims.
    monkeypatch.setattr(database, "get_user", lambda uid: None)
    resp = client.get("/api/v1/users/me", headers=_auth_headers())
    assert resp.status_code == 200
    assert resp.json()["user_id"] == "user-123"


def test_analysis_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(storage, "object_exists", lambda key: True)
    saved: dict[str, AnalysisResult] = {}

    def fake_save(result: AnalysisResult) -> AnalysisResult:
        saved[result.analysis_id] = result
        return result

    monkeypatch.setattr(database, "save_analysis", fake_save)

    resp = client.post(
        "/api/v1/analysis",
        headers=_auth_headers(),
        json={"object_key": "uploads/user-123/x.jpg", "analysis_types": ["skin", "makeup"]},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == AnalysisStatus.completed.value
    assert body["skin_metrics"]
    assert body["disclaimer"]
