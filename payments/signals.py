"""
post_save receiver that keeps Wallet.txn_count in sync with every
Transaction created through the ORM's normal save path (.create() / .save()).

Deliberately targets `txn_count`, not `balance` -- `balance` is already
mutated directly, under its own row lock, inside
payments/tasks.py:process_payment_event. A signal that also touched
`balance` would double-credit every wallet processed through that task.
This keeps the signal demo (this file) and the idempotency/locking demo
(payments/tasks.py) from stepping on each other.

Uses Wallet.objects.filter(...).update(...) rather than loading the wallet
and calling .save() on it -- an UPDATE queryset does NOT re-trigger
post_save, so this can't recurse into itself.

The gotcha this is built to demonstrate: bulk_create()/bulk_update() and
queryset.update() all bypass model signals entirely. A Transaction written
via bulk_create() lands in the ledger but never runs this receiver, so
Wallet.txn_count silently stops matching the ledger -- see
demo_django_signals.py for the captured proof.
"""

from django.db.models import F
from django.db.models.signals import post_save
from django.dispatch import receiver

from payments.models import Transaction, Wallet


@receiver(post_save, sender=Transaction)
def bump_wallet_txn_count(sender, instance, created, **kwargs):
    if not created:
        return
    Wallet.objects.filter(pk=instance.wallet_id).update(txn_count=F("txn_count") + 1)
