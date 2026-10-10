"""NotificationService: persisted in-app notifications that are also pushed live over the event bus."""

import pytest

from app.core.events import EventBus
from app.repositories.json_store import JsonStore
from app.repositories.notification_repository import NotificationRepository
from app.services.notification_service import NotificationService
from tests.helpers import EMPLOYEE_ID, MANAGER_ID


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.fixture
def service(store, bus) -> NotificationService:
    return NotificationService(NotificationRepository(store, max_per_user=50), bus)


def test_notify_persists_and_pushes_to_the_users_live_stream(service, bus, tmp_path):
    employee_stream, manager_stream = bus.subscribe(EMPLOYEE_ID), bus.subscribe(MANAGER_ID)

    note = service.notify(EMPLOYEE_ID, "Claim approved ✅", "EXP-2026-00001 was approved.", level="success",
                          link="/claims/clm-1")

    event = employee_stream.get_nowait()
    assert event["type"] == "notification"
    assert event["data"] == note.model_dump(mode="json")
    assert (event["data"]["title"], event["data"]["level"], event["data"]["read"]) == ("Claim approved ✅", "success", False)
    assert manager_stream.empty()
    persisted = NotificationRepository(JsonStore(tmp_path / "db.json"), max_per_user=50).for_user(EMPLOYEE_ID)
    assert [n.id for n in persisted] == [note.id]


def test_defaults_to_an_info_notification_without_a_link(service):
    note = service.notify(EMPLOYEE_ID, "Hello", "World")
    assert (note.level, note.link) == ("info", None)


def test_list_and_mark_read(service):
    first = service.notify(EMPLOYEE_ID, "First", "1")
    second = service.notify(EMPLOYEE_ID, "Second", "2")

    service.mark_read(EMPLOYEE_ID, first.id)
    assert [(n.title, n.read) for n in service.list(EMPLOYEE_ID)] == [("Second", False), ("First", True)]

    service.mark_read(EMPLOYEE_ID)
    assert all(n.read for n in service.list(EMPLOYEE_ID)) and second.read
    assert service.list(MANAGER_ID) == []
