from app.core.events import EventBus
from app.models.domain import Notification
from app.repositories.notification_repository import NotificationRepository


class NotificationService:
    def __init__(self, repository: NotificationRepository, bus: EventBus) -> None:
        self._repository = repository
        self._bus = bus

    def notify(
        self,
        user_id: str,
        title: str,
        message: str,
        level: str = "info",
        link: str | None = None,
    ) -> Notification:
        notification = self._repository.add(
            Notification(user_id=user_id, title=title, message=message, level=level, link=link)
        )
        self._bus.publish(user_id, "notification", notification.model_dump(mode="json"))
        return notification

    def list(self, user_id: str) -> list[Notification]:
        return self._repository.for_user(user_id)

    def mark_read(self, user_id: str, notification_id: str | None = None) -> None:
        self._repository.mark_read(user_id, notification_id)
