"""Composition root: builds every service once and wires dependencies."""

from functools import cached_property

from app.core.config import Settings, get_settings
from app.core.events import event_bus
from app.models.domain import Claim
from app.models.policy import Policy
from app.repositories.claim_repository import ClaimRepository
from app.repositories.json_store import JsonStore
from app.repositories.notification_repository import NotificationRepository
from app.repositories.user_repository import UserRepository
from app.services.agent_service import AgentService
from app.services.claim_service import ClaimService
from app.services.document_reader import DocumentReader
from app.services.duplicate_detector import DuplicateDetector
from app.services.extraction_service import ExtractionService
from app.services.llm import LLMRegistry
from app.services.notification_service import NotificationService
from app.services.policy_engine import PolicyEngine
from app.services.purpose_service import PurposeService
from app.services.question_engine import QuestionEngine
from app.services.reimbursement_gateway import MockReimbursementGateway


class Container:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.bus = event_bus

    def publish_claim(self, claim: Claim) -> None:
        self.bus.publish(claim.user_id, "claim.updated", claim.model_dump(mode="json"))

    @cached_property
    def store(self) -> JsonStore:
        return JsonStore(self.settings.resolve_path(self.settings.storage.database_file))

    @cached_property
    def users(self) -> UserRepository:
        return UserRepository(self.settings.resolve_path(self.settings.auth.users_file))

    @cached_property
    def claims(self) -> ClaimRepository:
        return ClaimRepository(self.store)

    @cached_property
    def policy(self) -> Policy:
        return Policy.load(self.settings.resolve_path(self.settings.policy.file))

    @cached_property
    def policy_engine(self) -> PolicyEngine:
        return PolicyEngine(
            self.policy, self.settings.app.base_currency, self.settings.pipeline.low_confidence_threshold
        )

    @cached_property
    def llm(self) -> LLMRegistry:
        return LLMRegistry(self.settings.llm)

    @cached_property
    def notifications(self) -> NotificationService:
        repo = NotificationRepository(self.store, self.settings.notifications.max_per_user)
        return NotificationService(repo, self.bus)

    @cached_property
    def claim_service(self) -> ClaimService:
        return ClaimService(
            policy=self.policy,
            engine=self.policy_engine,
            detector=DuplicateDetector(self.policy.duplicate_detection),
            questions=QuestionEngine(self.policy, self.policy_engine),
            claims=self.claims,
        )

    @cached_property
    def agent(self) -> AgentService:
        pipeline = self.settings.pipeline
        return AgentService(
            settings=self.settings,
            claims=self.claims,
            reader=DocumentReader(pipeline.pdf_render_dpi, pipeline.max_pdf_pages),
            extractor=ExtractionService(
                self.llm, self.policy, self.settings.app.base_currency, pipeline.verify_mode
            ),
            engine=self.policy_engine,
            claim_service=self.claim_service,
            notifications=self.notifications,
            registry=self.llm,
            purpose=PurposeService(self.llm, self.policy),
            users=self.users,
            publish=self.publish_claim,
        )

    @cached_property
    def gateway(self) -> MockReimbursementGateway:
        return MockReimbursementGateway(
            config=self.settings.reimbursement,
            currency=self.settings.app.base_currency,
            claims=self.claims,
            users=self.users,
            notifications=self.notifications,
            publish=self.publish_claim,
        )


container = Container(get_settings())
