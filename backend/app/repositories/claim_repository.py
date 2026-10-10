from app.models.domain import Claim, utcnow
from app.repositories.json_store import JsonStore


class ClaimRepository:
    def __init__(self, store: JsonStore) -> None:
        self._store = store
        self._claims: dict[str, Claim] = {
            cid: Claim.model_validate(raw) for cid, raw in store.collection("claims").items()
        }

    def get(self, claim_id: str) -> Claim | None:
        return self._claims.get(claim_id)

    def all(self) -> list[Claim]:
        return list(self._claims.values())

    def for_user(self, user_id: str) -> list[Claim]:
        claims = [c for c in self._claims.values() if c.user_id == user_id]
        return sorted(claims, key=lambda c: c.updated_at, reverse=True)

    def for_users(self, user_ids: set[str]) -> list[Claim]:
        claims = [c for c in self._claims.values() if c.user_id in user_ids]
        return sorted(claims, key=lambda c: c.updated_at, reverse=True)

    def save(self, claim: Claim) -> Claim:
        claim.updated_at = utcnow()
        self._claims[claim.id] = claim
        self._store.collection("claims")[claim.id] = claim.model_dump(mode="json")
        self._store.flush()
        return claim

    def delete(self, claim_id: str) -> None:
        self._claims.pop(claim_id, None)
        self._store.collection("claims").pop(claim_id, None)
        self._store.flush()

    def next_sequence(self) -> int:
        """Reserve the next reference number.

        A persisted counter (seeded from existing references) never goes back, so numbers are not reused
        when claims are deleted or resubmitted.
        """
        meta = self._store.collection("meta")
        highest = max((self._sequence_of(c.reference_no) for c in self._claims.values()), default=0)
        sequence = max(int(meta.get("reference_sequence", 0)), highest) + 1
        meta["reference_sequence"] = sequence
        self._store.flush()
        return sequence

    @staticmethod
    def _sequence_of(reference: str | None) -> int:
        tail = (reference or "").rsplit("-", 1)[-1]
        return int(tail) if tail.isdigit() else 0
