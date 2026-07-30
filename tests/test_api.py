"""HTTP contract tests for the session-based FaceByYou API."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.api.routes import admin, analytics, auth, uploads
from app.models.schemas import (
    AdminRole,
    AdminUser,
    AIFeedback,
    AnalysisResult,
    AnalysisStatus,
    CategoryScores,
    UserProfile,
)
from app.services import cleanup, database, face_analysis, storage
from app.services.feedback_engine import NvidiaFeedbackService

USER_ID = "user-123"
SESSION_ID = "session-123"


def make_result(score: float = 88.0) -> AnalysisResult:
    return AnalysisResult(
        analysis_id=f"analysis-{score}",
        user_id=USER_ID,
        session_id=SESSION_ID,
        status=AnalysisStatus.completed,
        category_scores=CategoryScores(
            foundation_score=score,
            blend_score=score,
            contour_score=score,
            eyes_score=score,
            lips_score=score,
            symmetry_score=score,
            base_finish_score=score,
            color_balance_score=score,
            overall_score=score,
        ),
        ai_feedback=AIFeedback(
            glam_type="soft_glam",
            strengths=["Even base"],
            improvements=["Blend contour"],
            recommendations=["Use a damp sponge"],
        ),
        confidence_score=95,
        created_at=datetime.now(UTC),
    )


def test_health(client) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_dev_login_returns_bearer_token(client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(database, "get_user", lambda _: None)
    monkeypatch.setattr(database, "upsert_user", lambda profile: profile)
    response = client.post(
        "/api/v1/auth/dev-login", json={"email": "test@facebyyou.ai", "user_id": USER_ID}
    )
    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"


def test_register_accepts_date_of_birth(client, monkeypatch: pytest.MonkeyPatch) -> None:
    class FirebaseUser:
        uid = USER_ID

    saved: list[UserProfile] = []
    monkeypatch.setattr(auth.firebase_auth, "create_user", lambda **_: FirebaseUser())
    monkeypatch.setattr(database, "upsert_user", lambda profile: saved.append(profile) or profile)
    response = client.post(
        "/api/v1/auth/register",
        json={
            "firstName": "Test",
            "lastName": "User",
            "dateOfBirth": "2000-01-02",
            "email": "test@facebyyou.ai",
            "password": "password123",
        },
    )
    assert response.status_code == 200
    assert str(saved[0].date_of_birth) == "2000-01-02"


def test_login_social_login_and_password_reset(client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        auth.firebase_auth,
        "verify_id_token",
        lambda _: {"uid": USER_ID, "email": "test@facebyyou.ai"},
    )
    monkeypatch.setattr(
        database,
        "get_user",
        lambda _: UserProfile(
            user_id=USER_ID, email="test@facebyyou.ai", status="PENDING_DELETION"
        ),
    )
    reactivated: list[str] = []
    monkeypatch.setattr(
        database, "reactivate_user_account", lambda user_id: reactivated.append(user_id)
    )

    async def reset(*_args, **_kwargs):
        return {}

    monkeypatch.setattr(auth, "_firebase_rest_call", reset)
    login = client.post("/api/v1/auth/login", json={"id_token": "firebase-token"})
    social = client.post("/api/v1/auth/google", json={"token": "firebase-token"})
    reset_response = client.post("/api/v1/auth/reset-password", json={"email": "test@facebyyou.ai"})
    assert login.status_code == social.status_code == reset_response.status_code == 200
    assert reactivated == [USER_ID, USER_ID]


def test_get_me_requires_auth(client) -> None:
    assert client.get("/api/v1/users/me").status_code == 401


def test_get_and_update_me(client, auth_headers, monkeypatch: pytest.MonkeyPatch) -> None:
    profile = UserProfile(user_id=USER_ID, email="test@facebyyou.ai", display_name="Before")
    monkeypatch.setattr(database, "get_user", lambda _: profile)
    monkeypatch.setattr(database, "upsert_user", lambda updated: updated)
    assert client.get("/api/v1/users/me", headers=auth_headers).status_code == 200
    response = client.put("/api/v1/users/me", headers=auth_headers, json={"display_name": "After"})
    assert response.status_code == 200
    assert response.json()["display_name"] == "After"


def test_user_deletion_is_scheduled(client, auth_headers, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}
    monkeypatch.setattr(database, "update_user_status", lambda **kwargs: captured.update(kwargs))
    response = client.delete("/api/v1/users/me", headers=auth_headers)
    assert response.status_code == 200
    assert captured["user_id"] == USER_ID
    assert captured["status"] == "PENDING_DELETION"


def test_backend_creates_session(client, auth_headers, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(database, "save_session", lambda **_: None)
    response = client.post("/api/v1/sessions", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["status"] == "OPEN"
    assert response.json()["session_id"]
    assert "urls" not in response.json()


def test_session_upload_returns_urls(client, auth_headers, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(database, "get_session", lambda _: {"user_id": USER_ID, "status": "OPEN"})
    monkeypatch.setattr(
        storage,
        "create_session_presigned_urls",
        lambda **_: {
            "front": {"url": "https://s3.test/front", "fields": {"key": "front.jpg"}},
            "left": {"url": "https://s3.test/left", "fields": {"key": "left.jpg"}},
            "right": {"url": "https://s3.test/right", "fields": {"key": "right.jpg"}},
        },
    )
    response = client.post(
        f"/api/v1/sessions/{SESSION_ID}/uploads",
        headers=auth_headers,
        json={
            "content_type": "image/jpeg",
            "files": {"front": "front.jpg", "left": "left.jpg", "right": "right.jpg"},
        },
    )
    assert response.status_code == 200
    assert set(response.json()["urls"]) == {"front", "left", "right"}


def test_refreshes_one_failed_upload_url(
    client, auth_headers, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(database, "get_session", lambda _: {"user_id": USER_ID, "status": "OPEN"})
    monkeypatch.setattr(
        storage,
        "create_session_presigned_url",
        lambda **_: {"url": "https://s3.test/right-retry", "fields": {"key": "right.jpg"}},
    )
    response = client.post(f"/api/v1/sessions/{SESSION_ID}/uploads/right", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["view"] == "right"
    assert response.json()["upload_url"] == "https://s3.test/right-retry"
    assert response.json()["upload_fields"]["key"] == "right.jpg"


def test_upload_rejects_wrong_media_type(
    client, auth_headers, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(database, "get_session", lambda _: {"user_id": USER_ID, "status": "OPEN"})
    response = client.post(
        f"/api/v1/sessions/{SESSION_ID}/uploads",
        headers=auth_headers,
        json={
            "content_type": "image/png",
            "files": {"front": "front.png", "left": "left.png", "right": "right.png"},
        },
    )
    assert response.status_code == 415


def test_upload_post_policy_enforces_jpeg_and_50_mb(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    class FakeS3:
        def generate_presigned_post(self, **kwargs):
            captured.update(kwargs)
            return {"url": "https://s3.test", "fields": {"key": kwargs["Key"]}}

    monkeypatch.setattr(storage, "s3_client", lambda: FakeS3())
    upload = storage.create_session_presigned_url(
        user_id=USER_ID, session_id=SESSION_ID, view="front"
    )
    assert upload["url"] == "https://s3.test"
    assert {"Content-Type": "image/jpeg"} in captured["Conditions"]
    assert ["content-length-range", 1, 50 * 1024 * 1024] in captured["Conditions"]


def test_upload_rejects_another_users_session(
    client, auth_headers, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        database, "get_session", lambda _: {"user_id": "other-user", "status": "OPEN"}
    )
    response = client.post(
        f"/api/v1/sessions/{SESSION_ID}/uploads",
        headers=auth_headers,
        json={
            "content_type": "image/jpeg",
            "files": {"front": "front.jpg", "left": "left.jpg", "right": "right.jpg"},
        },
    )
    assert response.status_code == 403


def test_upload_validation_is_session_scoped(
    client, auth_headers, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(database, "get_session", lambda _: {"user_id": USER_ID, "status": "OPEN"})
    monkeypatch.setattr(storage, "validate_uploaded_jpeg", lambda _: None)
    monkeypatch.setattr(uploads, "fetch_image_from_s3", lambda _: object())
    monkeypatch.setattr(
        uploads, "validate_image", lambda *_: {"success": True, "valid": True, "errors": []}
    )
    response = client.post(
        f"/api/v1/sessions/{SESSION_ID}/validate", headers=auth_headers, json={"view": "front"}
    )
    assert response.status_code == 200
    assert response.json()["valid"] is True


def test_upload_validation_returns_not_found_for_missing_session(
    client, auth_headers, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(database, "get_session", lambda _: None)
    response = client.post(
        f"/api/v1/sessions/{SESSION_ID}/validate", headers=auth_headers, json={"view": "front"}
    )
    assert response.status_code == 404


def test_analysis_requires_existing_session(
    client, auth_headers, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(database, "get_session", lambda _: None)
    assert (
        client.post(f"/api/v1/analysis/{SESSION_ID}", headers=auth_headers, json={}).status_code
        == 404
    )


def test_analysis_success(client, auth_headers, monkeypatch: pytest.MonkeyPatch) -> None:
    result = make_result()
    persistence_steps: list[str] = []
    monkeypatch.setattr(database, "get_session", lambda _: {"user_id": USER_ID, "status": "OPEN"})
    monkeypatch.setattr(storage, "validate_uploaded_jpeg", lambda _: None)
    monkeypatch.setattr(database, "log_uploaded_image", lambda **_: None)
    monkeypatch.setattr(
        database, "update_session_status", lambda *_: persistence_steps.append("lock")
    )
    monkeypatch.setattr(
        database, "save_analysis", lambda saved: persistence_steps.append("save") or saved
    )

    async def fake_analyze(**_) -> AnalysisResult:
        return result

    monkeypatch.setattr(face_analysis, "analyze", fake_analyze)
    response = client.post(f"/api/v1/analysis/{SESSION_ID}", headers=auth_headers, json={})
    assert response.status_code == 201
    assert response.json()["analysis_id"] == result.analysis_id
    assert persistence_steps == ["save", "lock"]


def test_analysis_rejects_an_oversized_or_wrong_type_upload(
    client, auth_headers, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi import HTTPException

    monkeypatch.setattr(database, "get_session", lambda _: {"user_id": USER_ID, "status": "OPEN"})
    monkeypatch.setattr(
        storage,
        "validate_uploaded_jpeg",
        lambda _: (_ for _ in ()).throw(
            HTTPException(status_code=413, detail="Image must be no larger than 50 MB")
        ),
    )
    response = client.post(f"/api/v1/analysis/{SESSION_ID}", headers=auth_headers, json={})
    assert response.status_code == 413


def test_analysis_list_and_detail(client, auth_headers, monkeypatch: pytest.MonkeyPatch) -> None:
    result = make_result()
    monkeypatch.setattr(database, "list_analyses", lambda *_args, **_kwargs: [result])
    monkeypatch.setattr(database, "get_analysis", lambda *_: result)
    assert len(client.get("/api/v1/analysis", headers=auth_headers).json()) == 1
    assert (
        client.get(f"/api/v1/analysis/{result.analysis_id}", headers=auth_headers).status_code
        == 200
    )


def test_analysis_session_history(client, auth_headers, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(database, "get_analyses_by_session", lambda **_: [make_result()])
    response = client.get(f"/api/v1/analysis/session/{SESSION_ID}", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()[0]["session_id"] == SESSION_ID


def test_history_trends(client, auth_headers, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(database, "get_user", lambda _: UserProfile(user_id=USER_ID, total_scans=2))
    monkeypatch.setattr(
        database, "list_analyses", lambda *_args, **_kwargs: [make_result(90), make_result(80)]
    )
    response = client.get("/api/v1/history/trends", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["categories"]["foundation"] == 10


def test_nim_fallback_without_api_key() -> None:
    service = NvidiaFeedbackService()
    service.client = None
    result = service.generate_feedback(
        {"image_urls": {"front": "x", "left": "y", "right": "z"}, "analysis_results": {}}
    )
    assert result["glam_type"] == "soft_glam"


def test_analytics_event(client, auth_headers, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}
    monkeypatch.setattr(
        analytics.database, "log_analytics_event", lambda *args: captured.update({"args": args})
    )
    response = client.post(
        "/api/v1/analytics/event", headers=auth_headers, json={"eventName": "scan_started"}
    )
    assert response.status_code == 200
    assert captured["args"][1] == "scan_started"


def test_admin_deletion_is_immediate(client, monkeypatch: pytest.MonkeyPatch) -> None:
    deleted: list[str] = []
    monkeypatch.setattr(database, "get_user", lambda _: UserProfile(user_id="target-user"))
    monkeypatch.setattr(database, "purge_user_data", lambda user_id: deleted.append(user_id))
    monkeypatch.setattr(database, "log_admin_action", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        admin.firebase_auth, "delete_user", lambda user_id: deleted.append(f"firebase:{user_id}")
    )
    from app.api.routes.admin import get_admin_writer
    from app.main import app

    app.dependency_overrides[get_admin_writer] = lambda: AdminUser(
        user_id="admin-1",
        email="admin@facebyyou.ai",
        role=AdminRole.ADMIN,
        created_at=datetime.now(UTC),
    )
    try:
        response = client.delete("/api/v1/admin/user/target-user")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert deleted == ["firebase:target-user", "target-user"]


def test_pending_deletion_cleanup_reads_all_scan_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    expired = "2000-01-01T00:00:00+00:00"
    calls: list[dict] = []

    class FakeTable:
        def scan(self, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                return {
                    "Items": [{"user_id": "first", "deletion_scheduled_at": expired}],
                    "LastEvaluatedKey": {"user_id": "first"},
                }
            return {"Items": [{"user_id": "second", "deletion_scheduled_at": expired}]}

    class FakeDynamo:
        def Table(self, _):
            return FakeTable()

    deleted: list[str] = []
    monkeypatch.setattr(cleanup.database, "dynamodb_resource", lambda: FakeDynamo())
    monkeypatch.setattr(cleanup.database, "purge_user_data", deleted.append)
    monkeypatch.setattr(cleanup.firebase_auth, "delete_user", lambda user_id: None)
    cleanup.process_pending_deletions()
    assert deleted == ["first", "second"]
    assert calls[1]["ExclusiveStartKey"] == {"user_id": "first"}


def test_admin_login_and_read_endpoints(client, monkeypatch: pytest.MonkeyPatch) -> None:
    admin_user = AdminUser(
        user_id="admin-1",
        email="admin@facebyyou.ai",
        role=AdminRole.ADMIN,
        created_at=datetime.now(UTC),
    )
    monkeypatch.setattr(admin.firebase_auth, "verify_id_token", lambda _: {"uid": "admin-1"})
    monkeypatch.setattr(database, "get_admin_user", lambda _: admin_user)
    monkeypatch.setattr(
        database,
        "get_platform_aggregates",
        lambda: {"total_users": 1, "daily_active_users": 1, "total_scans": 2, "average_score": 85},
    )
    monkeypatch.setattr(
        database, "get_all_users", lambda: [UserProfile(user_id=USER_ID, email="test@facebyyou.ai")]
    )
    monkeypatch.setattr(database, "get_user", lambda _: UserProfile(user_id=USER_ID, total_scans=2))
    monkeypatch.setattr(database, "get_user_images", lambda: [])
    from app.api.routes.admin import get_admin_reader
    from app.main import app

    app.dependency_overrides[get_admin_reader] = lambda: admin_user
    try:
        login = client.post("/api/v1/admin/admin-login", json={"id_token": "firebase-token"})
        metrics = client.get("/api/v1/admin/metrics")
        users_response = client.get("/api/v1/admin/users")
        user_detail = client.get(f"/api/v1/admin/users/{USER_ID}")
        images = client.get("/api/v1/admin/images")
    finally:
        app.dependency_overrides.clear()
    assert (
        login.status_code
        == metrics.status_code
        == users_response.status_code
        == user_detail.status_code
        == images.status_code
        == 200
    )


def test_admin_dev_login(client, monkeypatch: pytest.MonkeyPatch) -> None:
    admin_user = AdminUser(
        user_id="admin-1",
        email="admin@facebyyou.ai",
        role=AdminRole.ADMIN,
        created_at=datetime.now(UTC),
    )
    monkeypatch.setattr(database, "get_admin_by_email", lambda _: admin_user)
    response = client.post("/api/v1/admin/dev-login", json={"email": "admin@facebyyou.ai"})
    assert response.status_code == 200
    assert response.json()["role"] == "ADMIN"


def test_admin_deletes_image(client, monkeypatch: pytest.MonkeyPatch) -> None:
    deleted: list[tuple[str, str]] = []

    class FakeS3:
        def delete_object(self, *, Bucket: str, Key: str) -> None:
            deleted.append((Bucket, Key))

    writer = AdminUser(
        user_id="admin-1",
        email="admin@facebyyou.ai",
        role=AdminRole.ADMIN,
        created_at=datetime.now(UTC),
    )
    monkeypatch.setattr(
        database, "get_image_metadata", lambda _: {"image_url": "uploads/user-123/front.jpg"}
    )
    monkeypatch.setattr(database, "delete_image_record", lambda _: None)
    monkeypatch.setattr(database, "log_admin_action", lambda *args, **kwargs: None)
    monkeypatch.setattr(admin.boto3, "client", lambda _: FakeS3())
    from app.api.routes.admin import get_admin_writer
    from app.main import app

    app.dependency_overrides[get_admin_writer] = lambda: writer
    try:
        response = client.delete("/api/v1/admin/image/image-123")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert deleted[0][1] == "uploads/user-123/front.jpg"


def test_super_admin_team_management(client, monkeypatch: pytest.MonkeyPatch) -> None:
    super_admin = AdminUser(
        user_id="super-1",
        email="super@facebyyou.ai",
        role=AdminRole.SUPER_ADMIN,
        created_at=datetime.now(UTC),
    )

    class FirebaseUser:
        uid = "new-admin"

    monkeypatch.setattr(database, "get_all_admins", lambda: [super_admin])
    monkeypatch.setattr(database, "log_admin_action", lambda *args, **kwargs: None)
    monkeypatch.setattr(database, "create_admin_user", lambda *_: None)
    monkeypatch.setattr(database, "delete_admin_user", lambda *_: None)
    monkeypatch.setattr(admin.firebase_auth, "create_user", lambda **_: FirebaseUser())
    monkeypatch.setattr(
        admin.firebase_auth, "generate_password_reset_link", lambda _: "https://reset.test"
    )
    from app.api.routes.admin import get_super_admin
    from app.main import app

    app.dependency_overrides[get_super_admin] = lambda: super_admin
    try:
        team = client.get("/api/v1/admin/team")
        invite = client.post(
            "/api/v1/admin/invite", json={"email": "new@facebyyou.ai", "role": "ANALYST"}
        )
        revoke = client.delete("/api/v1/admin/access/new-admin")
    finally:
        app.dependency_overrides.clear()
    assert team.status_code == invite.status_code == revoke.status_code == 200
