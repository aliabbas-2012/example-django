from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db.models.signals import post_save

from payments.models import Transaction, Wallet
from payments.signals import bump_wallet_txn_count


class Command(BaseCommand):
    help = "Demonstrates Django signals: a post_save receiver that keeps Wallet.txn_count in sync, and the bulk_create/update gotcha that bypasses it."

    def add_arguments(self, parser):
        parser.add_argument(
            "--keep-data",
            action="store_true",
            help="Skip the final cleanup so the seeded Wallet/Transaction rows stay in the DB for inspection.",
        )

    def handle(self, *args, **options):
        Transaction.objects.filter(wallet__owner_id="signals-demo").delete()
        Wallet.objects.filter(owner_id="signals-demo").delete()
        wallet = Wallet.objects.create(owner_id="signals-demo", balance=Decimal("0.00"))

        self.stdout.write(self.style.MIGRATE_HEADING("1. Signal connected: Transaction.objects.create(...)"))
        Transaction.objects.create(wallet=wallet, event_id="sig-1", amount=Decimal("15.00"))
        wallet.refresh_from_db()
        self.stdout.write(f"  created a transaction -> wallet.txn_count = {wallet.txn_count} (receiver ran, no code here touched Wallet directly)")
        assert wallet.txn_count == 1

        self.stdout.write(self.style.MIGRATE_HEADING("2. Disconnect the receiver"))
        post_save.disconnect(bump_wallet_txn_count, sender=Transaction)
        Transaction.objects.create(wallet=wallet, event_id="sig-2", amount=Decimal("25.00"))
        wallet.refresh_from_db()
        self.stdout.write(f"  created another transaction with the receiver disconnected -> wallet.txn_count still {wallet.txn_count} (unchanged)")
        assert wallet.txn_count == 1

        self.stdout.write(self.style.MIGRATE_HEADING("3. Reconnect the receiver"))
        post_save.connect(bump_wallet_txn_count, sender=Transaction)
        Transaction.objects.create(wallet=wallet, event_id="sig-3", amount=Decimal("25.00"))
        wallet.refresh_from_db()
        self.stdout.write(f"  created another transaction -> wallet.txn_count = {wallet.txn_count} (receiver ran again)")
        assert wallet.txn_count == 2

        self.stdout.write(self.style.MIGRATE_HEADING("4. The gotcha: bulk_create() bypasses post_save entirely"))
        Transaction.objects.bulk_create([Transaction(wallet=wallet, event_id="sig-bulk-1", amount=Decimal("100.00"))])
        wallet.refresh_from_db()
        ledger_rows = Transaction.objects.filter(wallet=wallet).count()
        self.stdout.write(f"  bulk_create() a transaction -> wallet.txn_count still {wallet.txn_count}, but the ledger now has {ledger_rows} rows")
        assert wallet.txn_count == 2
        assert ledger_rows == 4

        self.stdout.write(self.style.SUCCESS("\nConfirmed: the receiver ran through .create()/.save(), and silently did not run through bulk_create()."))

        if options["keep_data"]:
            self.stdout.write(f"\n--keep-data: left wallet {wallet.owner_id!r} (pk={wallet.pk}) and its {ledger_rows} transactions in the DB.")
        else:
            Transaction.objects.filter(wallet=wallet).delete()
            wallet.delete()
