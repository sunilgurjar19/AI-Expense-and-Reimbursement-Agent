import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Request, status
from fastapi.responses import StreamingResponse

from app.api.deps import AppContainer, CurrentUser
from app.models.domain import Notification

router = APIRouter(tags=["notifications"])


@router.get("/notifications", response_model=list[Notification])
def list_notifications(user: CurrentUser, app: AppContainer) -> list[Notification]:
    return app.notifications.list(user.id)


@router.post("/notifications/read-all", status_code=status.HTTP_204_NO_CONTENT)
def mark_all_read(user: CurrentUser, app: AppContainer) -> None:
    app.notifications.mark_read(user.id)


@router.post("/notifications/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT)
def mark_read(notification_id: str, user: CurrentUser, app: AppContainer) -> None:
    app.notifications.mark_read(user.id, notification_id)


@router.get("/events/stream")
async def event_stream(request: Request, user: CurrentUser, app: AppContainer) -> StreamingResponse:
    """Server-sent events: live claim updates and notifications for the signed-in user."""
    heartbeat = app.settings.notifications.heartbeat_seconds

    async def stream() -> AsyncIterator[str]:
        queue = app.bus.subscribe(user.id)
        try:
            yield "event: ready\ndata: {}\n\n"
            while not await request.is_disconnected():
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=heartbeat)
                except TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                yield f"event: {event['type']}\ndata: {json.dumps(event['data'], default=str)}\n\n"
        finally:
            app.bus.unsubscribe(user.id, queue)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
