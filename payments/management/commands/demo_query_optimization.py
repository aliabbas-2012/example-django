from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import connection
from django.test.utils import CaptureQueriesContext

from payments.models import Transaction, Wallet


class Command(BaseCommand):
    help = "Demonstrates the N+1 query problem and how select_related/prefetch_related fix it."

    def handle(self, *args, **options):
        Transaction.objects.all().delete()
        Wallet.objects.all().delete()

        wallets = [Wallet.objects.create(owner_id=f"n1-user-{i}", balance=Decimal("0.00")) for i in range(10)]
        for w in wallets:
            for j in range(3):
                Transaction.objects.create(wallet=w, event_id=f"seed-{w.owner_id}-{j}", amount=Decimal("10.00"))

        self.stdout.write(self.style.MIGRATE_HEADING("Reverse FK: Wallet -> Transaction (multi-valued)"))
        self._n_plus_1_reverse()
        self._prefetch_related_fix()

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Forward FK: Transaction -> Wallet (single-valued)"))
        self._n_plus_1_forward()
        self._select_related_fix()

        Transaction.objects.filter(wallet__in=wallets).delete()
        for w in wallets:
            w.delete()

    def _n_plus_1_reverse(self):
        # 1 query for the wallet list, then 1 more query PER wallet when
        # `.transactions.all()` is touched inside the loop -> N+1.
        with CaptureQueriesContext(connection) as ctx:
            for wallet in Wallet.objects.filter(owner_id__startswith="n1-user-"):
                list(wallet.transactions.all())
        self.stdout.write(f"  without prefetch_related: {len(ctx.captured_queries)} queries")

    def _prefetch_related_fix(self):
        # 1 query for wallets + 1 query for ALL their transactions
        # (WHERE wallet_id IN (...)), joined together in Python -> 2 total,
        # regardless of how many wallets there are.
        with CaptureQueriesContext(connection) as ctx:
            for wallet in Wallet.objects.filter(owner_id__startswith="n1-user-").prefetch_related("transactions"):
                list(wallet.transactions.all())
        self.stdout.write(f"  with prefetch_related:    {len(ctx.captured_queries)} queries")

    def _n_plus_1_forward(self):
        # 1 query for the transaction list, then 1 more query PER row when
        # `.wallet.owner_id` is touched (each access re-fetches the
        # related Wallet by pk) -> N+1.
        with CaptureQueriesContext(connection) as ctx:
            for txn in Transaction.objects.filter(wallet__owner_id__startswith="n1-user-"):
                _ = txn.wallet.owner_id
        self.stdout.write(f"  without select_related:   {len(ctx.captured_queries)} queries")

    def _select_related_fix(self):
        # A single SQL JOIN pulls the related Wallet row into the same
        # result set -> 1 query total, no matter how many transactions.
        with CaptureQueriesContext(connection) as ctx:
            for txn in Transaction.objects.filter(wallet__owner_id__startswith="n1-user-").select_related("wallet"):
                _ = txn.wallet.owner_id
        self.stdout.write(f"  with select_related:      {len(ctx.captured_queries)} queries")
