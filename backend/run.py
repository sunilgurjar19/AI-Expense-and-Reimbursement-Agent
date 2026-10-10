"""Start the API using host/port from config/settings.yaml (or ERA_SERVER__* env vars)."""

import uvicorn

from app.core.config import get_settings

if __name__ == "__main__":
    server = get_settings().server
    # Live-update (SSE) connections never close on their own, so cap graceful shutdown;
    # otherwise auto-reload hangs while a browser tab is open.
    uvicorn.run(
        "app.main:app",
        host=server.host,
        port=server.port,
        reload=True,
        timeout_graceful_shutdown=3,
    )
