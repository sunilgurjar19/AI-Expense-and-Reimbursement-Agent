from app.models.domain import Notification
from app.repositories.json_store import JsonStore


class NotificationRepository:
    def __init__(self, store: JsonStore, max_per_user: int) -> None:
        self._store = store
        self._max_per_user = max_per_user
        raw = store.collection("notifications")
        self._items: dict[str, list[Notification]] = {
            uid: [Notification.model_validate(n) for n in items] for uid, items in raw.items()
        }

    def for_user(self, user_id: str) -> list[Notification]:
        return list(reversed(self._items.get(user_id, [])))

    def add(self, notification: Notification) -> Notification:
        items = self._items.setdefault(notification.user_id, [])
        items.append(notification)
        del items[: max(0, len(items) - self._max_per_user)]
        self._persist(notification.user_id)
        return notification

    def mark_read(self, user_id: str, notification_id: str | None = None) -> None:
        for item in self._items.get(user_id, []):
            if notification_id is None or item.id == notification_id:
                item.read = True
        self._persist(user_id)

    def _persist(self, user_id: str) -> None:
        self._store.collection("notifications")[user_id] = [
            n.model_dump(mode="json") for n in self._items.get(user_id, [])
        ]
        self._store.flush()
