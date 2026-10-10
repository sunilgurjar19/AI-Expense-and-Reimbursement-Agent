"""JSON-file persistence: JsonStore and the claim / notification / user repositories."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.models.domain import Notification
from app.repositories.claim_repository import ClaimRepository
from app.repositories.json_store import JsonStore
from app.repositories.notification_repository import NotificationRepository
from app.repositories.user_repository import UserRepository
from tests.helpers import BACKEND_DIR, EMPLOYEE_ID, MANAGER_ID, PRIYA_ID, make_claim, make_receipt


class TestJsonStore:
    def test_a_missing_file_is_an_empty_store_until_flushed(self, tmp_path):
        path = tmp_path / "nested" / "db.json"
        store = JsonStore(path)
        claims = store.collection("claims")
        assert claims == {} and store.collection("claims") is claims
        assert not path.exists()

    def test_flush_writes_atomically_and_round_trips(self, tmp_path):
        path = tmp_path / "nested" / "dir" / "db.json"
        store = JsonStore(path)
        store.collection("claims")["c1"] = {"title": "Pune trip", "total": 12.5}
        store.flush()

        assert json.loads(path.read_text(encoding="utf-8")) == {"claims": {"c1": {"title": "Pune trip", "total": 12.5}}}
        assert [p.name for p in path.parent.iterdir()] == ["db.json"]  # the temp file was renamed into place
        assert JsonStore(path).collection("claims") == {"c1": {"title": "Pune trip", "total": 12.5}}

    def test_values_json_cannot_encode_are_stringified(self, tmp_path):
        store = JsonStore(tmp_path / "db.json")
        store.collection("misc")["when"] = datetime(2026, 10, 5, 9, 30, tzinfo=timezone.utc)
        store.flush()
        assert JsonStore(tmp_path / "db.json").collection("misc") == {"when": "2026-10-05 09:30:00+00:00"}

    def test_unicode_is_preserved(self, tmp_path):
        store = JsonStore(tmp_path / "db.json")
        store.collection("claims")["c1"] = {"vendor": "मनिष सर्विस सेंटर ₹"}
        store.flush()
        assert JsonStore(tmp_path / "db.json").collection("claims")["c1"]["vendor"] == "मनिष सर्विस सेंटर ₹"


class TestClaimRepository:
    def test_save_persists_and_touches_updated_at(self, tmp_path):
        repo = ClaimRepository(JsonStore(tmp_path / "db.json"))
        claim = make_claim(make_receipt(vendor="Taj"), title="Bengaluru trip")
        before = claim.updated_at

        assert repo.save(claim) is claim and claim.updated_at >= before

        reloaded = ClaimRepository(JsonStore(tmp_path / "db.json")).get(claim.id)
        assert reloaded is not claim
        assert reloaded.model_dump() == claim.model_dump()

    def test_queries_by_user_are_newest_first(self, claim_repo):
        old, new, other = make_claim(title="old"), make_claim(title="new"), make_claim(title="priya", user_id=PRIYA_ID)
        for claim in (old, new, other):
            claim_repo.save(claim)
        base = datetime(2026, 10, 1, tzinfo=timezone.utc)
        old.updated_at, new.updated_at, other.updated_at = base, base + timedelta(hours=1), base + timedelta(hours=2)

        assert [c.title for c in claim_repo.for_user(EMPLOYEE_ID)] == ["new", "old"]
        assert [c.title for c in claim_repo.for_users({EMPLOYEE_ID, PRIYA_ID})] == ["priya", "new", "old"]
        assert claim_repo.for_users(set()) == []
        assert {c.title for c in claim_repo.all()} == {"old", "new", "priya"}

    def test_delete_removes_from_memory_and_disk(self, tmp_path):
        repo = ClaimRepository(JsonStore(tmp_path / "db.json"))
        claim = repo.save(make_claim())
        repo.delete(claim.id)
        repo.delete("clm-does-not-exist")  # no error
        assert repo.get(claim.id) is None
        assert ClaimRepository(JsonStore(tmp_path / "db.json")).all() == []

    def test_next_sequence_reserves_increasing_numbers(self, claim_repo):
        assert claim_repo.next_sequence() == 1
        claim_repo.save(make_claim(reference_no="EXP-2026-00001"))
        claim_repo.save(make_claim())
        assert claim_repo.next_sequence() == 2
        assert claim_repo.next_sequence() == 3  # a reserved number is never handed out twice

    def test_numbers_are_not_reused_after_a_deletion_or_a_restart(self, tmp_path):
        repo = ClaimRepository(JsonStore(tmp_path / "db.json"))
        repo.save(make_claim(reference_no=f"EXP-2026-{repo.next_sequence():05d}"))
        latest = repo.save(make_claim(reference_no=f"EXP-2026-{repo.next_sequence():05d}"))
        repo.delete(latest.id)

        assert ClaimRepository(JsonStore(tmp_path / "db.json")).next_sequence() == 3

    def test_the_counter_continues_after_existing_references(self, claim_repo):
        # e.g. a database written before the counter existed
        claim_repo.save(make_claim(reference_no="EXP-2026-00007"))
        claim_repo.save(make_claim(reference_no="legacy"))
        assert claim_repo.next_sequence() == 8


class TestNotificationRepository:
    @staticmethod
    def note(user_id: str = EMPLOYEE_ID, title: str = "Hi") -> Notification:
        return Notification(user_id=user_id, title=title, message=f"{title} message")

    def test_newest_notifications_come_first_per_user(self, store):
        repo = NotificationRepository(store, max_per_user=10)
        for title in ("first", "second"):
            repo.add(self.note(title=title))
        repo.add(self.note(user_id=MANAGER_ID, title="for manager"))
        assert [n.title for n in repo.for_user(EMPLOYEE_ID)] == ["second", "first"]
        assert [n.title for n in repo.for_user(MANAGER_ID)] == ["for manager"]
        assert repo.for_user(PRIYA_ID) == []

    def test_only_the_latest_notifications_are_kept(self, store):
        repo = NotificationRepository(store, max_per_user=3)
        for number in range(5):
            repo.add(self.note(title=f"n{number}"))
        assert [n.title for n in repo.for_user(EMPLOYEE_ID)] == ["n4", "n3", "n2"]

    def test_mark_read_one_or_all_and_persist(self, tmp_path):
        store = JsonStore(tmp_path / "db.json")
        repo = NotificationRepository(store, max_per_user=10)
        first, second, third = (repo.add(self.note(title=t)) for t in ("a", "b", "c"))

        repo.mark_read(EMPLOYEE_ID, second.id)
        repo.mark_read(EMPLOYEE_ID, "ntf-unknown")
        assert [n.read for n in repo.for_user(EMPLOYEE_ID)] == [False, True, False]

        repo.mark_read(EMPLOYEE_ID)
        reloaded = NotificationRepository(JsonStore(tmp_path / "db.json"), max_per_user=10)
        assert [(n.id, n.read) for n in reloaded.for_user(EMPLOYEE_ID)] == [(third.id, True), (second.id, True),
                                                                            (first.id, True)]


class TestUserRepository:
    @pytest.fixture
    def users(self) -> UserRepository:
        return UserRepository(BACKEND_DIR / "data" / "users.json")

    def test_demo_users_are_loaded(self, users):
        assert [u.id for u in users.all()] == [EMPLOYEE_ID, PRIYA_ID, MANAGER_ID]
        manager = users.get(MANAGER_ID)
        assert (manager.name, manager.role, manager.manager_id) == ("Meera Iyer", "manager", None)
        assert users.get("u-9999") is None

    @pytest.mark.parametrize(("username", "user_id"), [("employee", EMPLOYEE_ID), ("  PRIYA ", PRIYA_ID),
                                                       ("Manager", MANAGER_ID), ("nobody", None)])
    def test_username_lookup_ignores_case_and_whitespace(self, users, username, user_id):
        user = users.by_username(username)
        assert (user.id if user else None) == user_id

    def test_reporting_lines(self, users):
        assert [u.id for u in users.reports_of(MANAGER_ID)] == [EMPLOYEE_ID, PRIYA_ID]
        assert users.reports_of(EMPLOYEE_ID) == []
