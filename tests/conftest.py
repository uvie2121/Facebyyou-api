"""Test-wide environment overrides applied before application imports."""

import os
from unittest.mock import patch

import firebase_admin
import pytest
from fastapi.testclient import TestClient
from firebase_admin import credentials

os.environ["DEBUG"] = "false"
os.environ.pop("NIM_API_KEY", None)
os.environ["FIREBASE_ADMIN_CREDENTIALS_PATH"] = __file__

with (
    patch.object(credentials, "Certificate", return_value=object()),
    patch.object(firebase_admin, "initialize_app"),
):
    from app.main import app
from app.services import database


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth_headers(client, monkeypatch):
    monkeypatch.setattr(database, "get_user", lambda _: None)
    monkeypatch.setattr(database, "upsert_user", lambda profile: profile)
    response = client.post(
        "/api/v1/auth/dev-login",
        json={"email": "test@facebyyou.ai", "user_id": "user-123"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}
