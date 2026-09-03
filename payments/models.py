from django.db import models


class Wallet(models.Model):
    """The row that gets mutated. Row-level locking protects its balance."""

    owner_id = models.CharField(max_length=64, unique=True)
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # Maintained only by payments/signals.py's post_save receiver on
    # Transaction -- kept separate from `balance` on purpose, since
    # `balance` is already mutated directly (with its own row lock) inside
    # payments/tasks.py:process_payment_event. A signal that also touched
    # `balance` would double-credit every wallet processed through that
    # task. See demo_django_signals.py.
    txn_count = models.PositiveIntegerField(default=0)

    def __str__(self) -> str:
        return f"Wallet({self.owner_id}) = {self.balance}"


class ProcessedEvent(models.Model):
    """
    Idempotency ledger. One row per successfully processed event.

    `event_id` is whatever uniquely identifies the unit of work upstream
    (a payment-gateway event id, a message id, or hash(payload) if the
    source doesn't hand you one). The unique constraint is what actually
    enforces "exactly-once effect" -- a second INSERT for the same
    event_id raises IntegrityError, which is how the task detects a
    duplicate delivery.
    """

    event_id = models.CharField(max_length=128, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.event_id


class Transaction(models.Model):
    """
    Ledger line for a single credit. Exists to demonstrate the N+1 query
    problem: `wallet` is the single-valued side (fixed with
    select_related), and `Wallet.transactions` (the reverse FK) is the
    multi-valued side (fixed with prefetch_related).
    """

    wallet = models.ForeignKey(Wallet, related_name="transactions", on_delete=models.CASCADE)
    event_id = models.CharField(max_length=128)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"Transaction({self.wallet.owner_id}, {self.amount})"
