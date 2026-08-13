from datetime import datetime, timezone
import pytest
from pydantic import ValidationError
from app.schemas import (
    CreateUserAdminRequest,
    UpdateUserAdminRequest,
    DashboardStatsResponse,
    ChatSessionAudit,
    ChatMessageAudit,
    SyncHistoryItem,
)


def test_create_user_admin_request_validation() -> None:
    # Test valid request
    req = CreateUserAdminRequest(
        username="newuser",
        password="password123",
        role="editor",
        is_active=True,
    )
    assert req.username == "newuser"
    assert req.role == "editor"
    assert req.is_active is True

    # Test default values
    req_default = CreateUserAdminRequest(
        username="defaultuser",
        password="password123",
    )
    assert req_default.role == "reader"
    assert req_default.is_active is True

    # Test missing username
    with pytest.raises(ValidationError):
        CreateUserAdminRequest(password="password123")


def test_update_user_admin_request_validation() -> None:
    # Test partial updates
    req = UpdateUserAdminRequest(role="admin")
    assert req.role == "admin"
    assert req.password is None
    assert req.is_active is None

    req_empty = UpdateUserAdminRequest()
    assert req_empty.role is None
    assert req_empty.password is None


def test_dashboard_stats_response() -> None:
    stats = DashboardStatsResponse(
        total_folders=5,
        total_files=20,
        total_users=3,
        total_conversations=10,
        failed_syncs=1,
    )
    assert stats.total_folders == 5
    assert stats.total_files == 20
    assert stats.failed_syncs == 1


def test_chat_session_audit_validation() -> None:
    now = datetime.now(timezone.utc)
    audit = ChatSessionAudit(
        session_id="session-xyz",
        username="testuser",
        user_id=1,
        message_count=4,
        latest_message_time=now,
    )
    assert audit.session_id == "session-xyz"
    assert audit.message_count == 4
    assert audit.latest_message_time == now


def test_chat_message_audit_validation() -> None:
    now = datetime.now(timezone.utc)
    msg = ChatMessageAudit(
        id=123,
        role="user",
        content="hello assistant",
        created_at=now,
    )
    assert msg.id == 123
    assert msg.role == "user"
    assert msg.content == "hello assistant"


def test_sync_history_item_validation() -> None:
    now = datetime.now(timezone.utc)
    item = SyncHistoryItem(
        id=1,
        doc_id="550e8400-e29b-41d4-a716-446655440000",
        file_id=10,
        status="completed",
        error_message=None,
        content_hash=None,
        created_at=now,
        updated_at=now,
    )
    assert item.id == 1
    assert item.status == "completed"
    assert item.doc_id == "550e8400-e29b-41d4-a716-446655440000"
