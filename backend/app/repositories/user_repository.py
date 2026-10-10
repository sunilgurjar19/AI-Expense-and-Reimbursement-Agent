import json
from pathlib import Path

from app.models.domain import User


class UserRepository:
    """Read-only user directory backed by a JSON file."""

    def __init__(self, users_file: Path) -> None:
        with users_file.open(encoding="utf-8") as fh:
            self._users = {u["id"]: User(**u) for u in json.load(fh)}

    def all(self) -> list[User]:
        return list(self._users.values())

    def get(self, user_id: str) -> User | None:
        return self._users.get(user_id)

    def by_username(self, username: str) -> User | None:
        username = username.strip().lower()
        return next((u for u in self._users.values() if u.username.lower() == username), None)

    def reports_of(self, manager_id: str) -> list[User]:
        return [u for u in self._users.values() if u.manager_id == manager_id]
