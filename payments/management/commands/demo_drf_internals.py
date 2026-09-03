from decimal import Decimal

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from rest_framework.test import APIClient

from config.urls import router
from payments.models import Wallet
from payments.serializers import CreditWalletRequestSerializer


class Command(BaseCommand):
    help = "Demonstrates DRF internals: router-generated URLs, authentication (401) vs object-level permissions (403), and serializer validation."

    def add_arguments(self, parser):
        parser.add_argument(
            "--keep-data",
            action="store_true",
            help="Skip the final cleanup so the seeded users/wallets stay in the DB for inspection.",
        )

    def handle(self, *args, **options):
        for username in ("drf-demo-alice", "drf-demo-bob"):
            User.objects.filter(username=username).delete()
        Wallet.objects.filter(owner_id__in=["drf-demo-alice", "drf-demo-bob"]).delete()

        self.stdout.write(self.style.MIGRATE_HEADING("1. The router builds these URLs from WalletViewSet alone -- no manual path() for any of them"))
        for url_pattern in router.urls:
            if url_pattern.name == "api-root" or "format" in str(url_pattern.pattern):
                continue
            self.stdout.write(f"  {url_pattern.name:14s} {url_pattern.pattern}")

        alice = User.objects.create_user(username="drf-demo-alice", password="demo-pass-123")
        User.objects.create_user(username="drf-demo-bob", password="demo-pass-123")
        alice_wallet = Wallet.objects.create(owner_id="drf-demo-alice", balance=Decimal("0.00"))
        bob_wallet = Wallet.objects.create(owner_id="drf-demo-bob", balance=Decimal("0.00"))

        client = APIClient()

        self.stdout.write(self.style.MIGRATE_HEADING("2. No token at all -- DRF can't tell who this is (authentication, not permissions)"))
        resp = client.get("/api/wallets/")
        self.stdout.write(f"  GET /api/wallets/ (no token) -> {resp.status_code}")
        assert resp.status_code == 401

        resp = client.post("/api/token/", {"username": "drf-demo-alice", "password": "demo-pass-123"}, format="json")
        access = resp.data["access"]
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

        self.stdout.write(self.style.MIGRATE_HEADING("3. Valid token, but crediting someone ELSE's wallet -- DRF knows exactly who this is, and says no (permissions, not authentication)"))
        resp = client.post(f"/api/wallets/{bob_wallet.pk}/credit/", {"event_id": "drf-evt-1", "amount": "10.00"}, format="json")
        self.stdout.write(f"  alice's token, POST .../wallets/{bob_wallet.pk}/credit/ (bob's wallet) -> {resp.status_code}")
        assert resp.status_code == 403

        self.stdout.write(self.style.MIGRATE_HEADING("4. Same token, her OWN wallet -- authenticated AND permitted"))
        resp = client.post(f"/api/wallets/{alice_wallet.pk}/credit/", {"event_id": "drf-evt-2", "amount": "10.00"}, format="json")
        self.stdout.write(f"  alice's token, POST .../wallets/{alice_wallet.pk}/credit/ (her own wallet) -> {resp.status_code}")
        assert resp.status_code == 202

        self.stdout.write(self.style.MIGRATE_HEADING("5. Serializer validation, with no view involved at all"))
        bad = CreditWalletRequestSerializer(data={"event_id": "drf-evt-3", "amount": "not-a-number"})
        self.stdout.write(f"  CreditWalletRequestSerializer(amount='not-a-number').is_valid() -> {bad.is_valid()}")
        self.stdout.write(f"  .errors -> {bad.errors}")
        assert not bad.is_valid()
        assert "amount" in bad.errors

        self.stdout.write(self.style.SUCCESS(
            "\nConfirmed: 401 means DRF doesn't know who you are, 403 means it knows and says no, "
            "and serializer validation runs independently of any of that."
        ))

        if options["keep_data"]:
            self.stdout.write(f"\n--keep-data: left users drf-demo-alice/drf-demo-bob and their wallets in the DB.")
        else:
            for username in ("drf-demo-alice", "drf-demo-bob"):
                User.objects.filter(username=username).delete()
            Wallet.objects.filter(owner_id__in=["drf-demo-alice", "drf-demo-bob"]).delete()
