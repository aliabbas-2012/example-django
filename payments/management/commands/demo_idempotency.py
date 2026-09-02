import threading
from decimal import Decimal

from django import db
from django.core.management.base import BaseCommand

from payments.models import ProcessedEvent, Wallet
from payments.tasks import process_payment_event


class Command(BaseCommand):
    help = "Demonstrates idempotency (duplicate event delivery) and race-safety (select_for_update)."

    def handle(self, *args, **options):
        Wallet.objects.filter(owner_id__startswith="idem-").delete()
        ProcessedEvent.objects.filter(event_id__startswith="idem-").delete()

        self.stdout.write(self.style.MIGRATE_HEADING("1. Same event delivered 3 times (at-least-once redelivery)"))
        wallet = Wallet.objects.create(owner_id="idem-dup-test", balance=Decimal("0.00"))
        for i in range(3):
            result = process_payment_event.run("idem-evt-1", "idem-dup-test", Decimal("50.00"))
            self.stdout.write(f"  delivery {i + 1}: {result}")
        wallet.refresh_from_db()
        self.stdout.write(f"  final balance: {wallet.balance} (expected 50.00, NOT 150.00)")
        assert wallet.balance == Decimal("50.00")

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("2. 20 concurrent DISTINCT events on the same wallet (race condition check)"))
        wallet = Wallet.objects.create(owner_id="idem-race-test", balance=Decimal("0.00"))
        n = 20

        def worker(i):
            db.connections.close_all()  # each thread needs its own DB connection
            process_payment_event.run(f"idem-evt-race-{i}", "idem-race-test", Decimal("1.00"))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        wallet.refresh_from_db()
        expected = Decimal(n) * Decimal("1.00")
        self.stdout.write(f"  final balance: {wallet.balance} (expected {expected} -- select_for_update prevents lost updates)")
        assert wallet.balance == expected

        Wallet.objects.filter(owner_id__startswith="idem-").delete()
        ProcessedEvent.objects.filter(event_id__startswith="idem-").delete()
        self.stdout.write(self.style.SUCCESS("\nAll assertions passed."))
