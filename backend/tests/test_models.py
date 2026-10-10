"""Domain models and API schemas: invariants the rest of the app relies on."""

import pytest

from app.models.api import ClaimSummary, UserPublic
from app.models.domain import (
    EDITABLE_STATUSES,
    PIPELINE_STAGES,
    Claim,
    ClaimStatus,
    Question,
    ReceiptStage,
    User,
    new_id,
)
from app.models.policy import Policy
from tests.helpers import POLICY_FILE, make_claim, make_receipt


class TestClaim:
    def test_claims_saved_before_purpose_source_existed_count_as_employee_written(self):
        legacy = Claim.model_validate({"id": "clm-old", "user_id": "u-1001", "purpose": "Client visit"})
        assert legacy.purpose_source == "user"
        assert Claim.model_validate({"id": "clm-new", "user_id": "u-1001"}).purpose_source is None
        agent_written = Claim.model_validate({"user_id": "u-1001", "purpose": "x", "purpose_source": "agent"})
        assert agent_written.purpose_source == "agent"

    def test_receipt_lookup_and_active_receipts(self):
        kept, removed = make_receipt(), make_receipt(excluded=True)
        claim = make_claim(kept, removed)
        assert claim.receipt(removed.id) is removed and claim.receipt("rcpt-missing") is None
        assert claim.active_receipts == [kept]

    @pytest.mark.parametrize("status", list(ClaimStatus))
    def test_only_unsubmitted_claims_are_editable(self, status):
        claim = make_claim(status=status)
        assert claim.is_editable is (status in {"draft", "processing", "needs_attention", "ready"})
        assert (status in EDITABLE_STATUSES) is claim.is_editable

    def test_new_objects_get_prefixed_unique_ids(self):
        assert make_claim().id.startswith("clm-") and make_receipt().id.startswith("rcpt-")
        assert Question(key="k", kind="vendor", prompt="?").id.startswith("q-")
        assert len({new_id("x") for _ in range(200)}) == 200


def test_pipeline_stages_are_listed_in_processing_order():
    assert [s.value for s in PIPELINE_STAGES] == [
        "uploaded", "reading", "extracting", "verifying", "categorising", "validating", "duplicate_check", "completed"]
    assert ReceiptStage.FAILED not in PIPELINE_STAGES


def test_public_user_profile_never_exposes_the_password():
    user = User(id="u-1", username="asha", password="secret", name="Asha", email="a@x", role="employee",
                department="Ops", employee_code="E-1", manager_id="u-2")
    public = UserPublic.from_user(user).model_dump()
    assert "password" not in public and "manager_id" not in public
    assert public["username"] == "asha"


def test_claim_summary_counts_active_receipts_and_open_questions():
    claim = make_claim(make_receipt(), make_receipt(excluded=True), title="Pune trip", reference_no="EXP-2026-00007",
                       total_claimed=900.0, total_reimbursable=800.0, readiness=67)
    claim.questions = [Question(key="a", kind="purpose", prompt="?"), Question(key="b", kind="vendor", prompt="?")]
    summary = ClaimSummary.from_claim(claim, owner_name="Aarav Sharma")
    assert (summary.receipt_count, summary.pending_questions, summary.owner_name) == (1, 2, "Aarav Sharma")
    assert (summary.reference_no, summary.total_reimbursable, summary.readiness) == ("EXP-2026-00007", 800.0, 67)


def test_policy_file_loads_with_unique_categories():
    policy = Policy.load(POLICY_FILE)
    keys = [c.key for c in policy.categories]
    assert len(keys) == len(set(keys)) and "other" in keys
    assert policy.fx_rates["INR"] == 1 and policy.category("lodging").limit_per_item == 9000
    assert policy.category(None) is None and policy.category("missing") is None
