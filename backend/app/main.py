import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import approvals, auth, claims, dashboard, meta, notifications, settings
from app.container import container
from app.services.agent_service import ClaimLockedError, UploadError
from app.services.claim_service import AnswerError
from app.services.reimbursement_gateway import GatewayError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    container.agent.resume_interrupted()
    container.gateway.resume_pending_payouts()
    logging.getLogger("app").info("LLM provider: %s", container.llm.active)
    yield


def create_app() -> FastAPI:
    config = container.settings
    app = FastAPI(title=config.app.name, version="1.0.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.server.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition"],
    )

    error_status = {
        AnswerError: status.HTTP_422_UNPROCESSABLE_CONTENT,
        UploadError: status.HTTP_400_BAD_REQUEST,
        ClaimLockedError: status.HTTP_409_CONFLICT,
        GatewayError: status.HTTP_409_CONFLICT,
    }
    for exc_type, code in error_status.items():
        app.add_exception_handler(exc_type, _error_handler(code))

    for module in (auth, meta, claims, approvals, notifications, dashboard, settings):
        app.include_router(module.router, prefix=config.server.api_prefix)
    return app


def _error_handler(code: int):
    async def handler(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=code, content={"detail": str(exc)})

    return handler


app = create_app()
