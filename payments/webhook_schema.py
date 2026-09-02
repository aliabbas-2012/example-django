"""
Python 3.13 typing features, applied to validating an inbound gateway
webhook payload before it's trusted enough to dispatch as a Celery task.

- `ReadOnly[...]` (PEP 705) marks these TypedDict keys as non-assignable
  after construction -- appropriate here because a webhook payload is a
  fact you received, not a struct you mutate. Assigning
  `payload["amount"] = "..."` would now be a type-checker error.

- `TypeIs[...]` (PEP 742) is what makes `is_payment_event_payload` a
  *narrowing* check instead of just a bool-returning function. A plain
  `-> bool` gives a type checker nothing: inside `if is_valid(data):`,
  `data` is still typed as `object`. `-> TypeIs[PaymentEventPayload]`
  tells the checker that once this returns True, `data` is narrowed to
  `PaymentEventPayload` for the rest of that branch -- so
  `data["event_id"]` is known to be `str` with no further isinstance
  checks or casts.
"""

from typing import ReadOnly, TypedDict, TypeIs


class PaymentEventPayload(TypedDict):
    event_id: ReadOnly[str]
    owner_id: ReadOnly[str]
    amount: ReadOnly[str]


def is_payment_event_payload(data: object) -> TypeIs[PaymentEventPayload]:
    return (
        isinstance(data, dict)
        and isinstance(data.get("event_id"), str)
        and isinstance(data.get("owner_id"), str)
        and isinstance(data.get("amount"), str)
    )
