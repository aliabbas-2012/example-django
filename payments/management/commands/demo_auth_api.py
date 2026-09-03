from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from rest_framework.test import APIClient

from payments.models import Wallet


class Command(BaseCommand):
    help = "Demonstrates the full auth + wallet API: register, login, me, create/update/delete a wallet, and logout-blacklists-the-refresh-token."

    def add_arguments(self, parser):
        parser.add_argument(
            "--keep-data",
            action="store_true",
            help="Skip the final cleanup so the seeded users/wallets stay in the DB for inspection.",
        )

    def handle(self, *args, **options):
        for username in ("api-demo-carol", "api-demo-dave"):
            User.objects.filter(username=username).delete()
        Wallet.objects.filter(owner_id__in=["api-demo-carol", "api-demo-dave"]).delete()

        client = APIClient()

        self.stdout.write(self.style.MIGRATE_HEADING("1. Register -- creates the User AND a zero-balance Wallet in one call"))
        resp = client.post(
            "/api/auth/register/",
            {"username": "api-demo-carol", "password": "pass-12345", "email": "carol@example.com"},
            format="json",
        )
        self.stdout.write(f"  POST /api/auth/register/ -> {resp.status_code}: {resp.data}")
        assert resp.status_code == 201
        assert resp.data["wallet"]["balance"] == "0.00"
        client.post("/api/auth/register/", {"username": "api-demo-dave", "password": "pass-12345"}, format="json")

        self.stdout.write(self.style.MIGRATE_HEADING("2. Login, then /me -- one call to see who you are and your wallet together"))
        resp = client.post("/api/token/", {"username": "api-demo-carol", "password": "pass-12345"}, format="json")
        access, refresh = resp.data["access"], resp.data["refresh"]
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        resp = client.get("/api/auth/me/")
        self.stdout.write(f"  GET /api/auth/me/ -> {resp.status_code}: {resp.data}")
        assert resp.status_code == 200
        carol_wallet_id = resp.data["wallet"]["id"]

        self.stdout.write(self.style.MIGRATE_HEADING("3. Registering again already made a wallet -- a second POST hits the unique constraint, cleanly"))
        resp = client.post("/api/wallets/", {}, format="json")
        self.stdout.write(f"  POST /api/wallets/ (already have one) -> {resp.status_code}: {resp.data}")
        assert resp.status_code == 400

        self.stdout.write(self.style.MIGRATE_HEADING("4. Trying to PATCH your own balance directly -- read-only field, silently has no effect"))
        resp = client.patch(f"/api/wallets/{carol_wallet_id}/", {"balance": "999999.00"}, format="json")
        wallet = Wallet.objects.get(pk=carol_wallet_id)
        self.stdout.write(f"  PATCH /api/wallets/{carol_wallet_id}/ balance=999999.00 -> {resp.status_code}, actual DB balance is still {wallet.balance}")
        assert resp.status_code == 200
        assert wallet.balance == 0

        self.stdout.write(self.style.MIGRATE_HEADING("5. Trying to touch DAVE's wallet -- same IsWalletOwner check from Q13, now guarding update/destroy too"))
        dave_wallet = Wallet.objects.get(owner_id="api-demo-dave")
        resp = client.patch(f"/api/wallets/{dave_wallet.pk}/", {"balance": "1.00"}, format="json")
        self.stdout.write(f"  carol's token, PATCH dave's wallet -> {resp.status_code}")
        assert resp.status_code == 403
        resp = client.delete(f"/api/wallets/{dave_wallet.pk}/")
        self.stdout.write(f"  carol's token, DELETE dave's wallet -> {resp.status_code}")
        assert resp.status_code == 403

        self.stdout.write(self.style.MIGRATE_HEADING("6. Deleting HER OWN wallet -- same check, this time it's actually her wallet"))
        resp = client.delete(f"/api/wallets/{carol_wallet_id}/")
        self.stdout.write(f"  carol's token, DELETE her own wallet -> {resp.status_code}")
        assert resp.status_code == 204

        self.stdout.write(self.style.MIGRATE_HEADING("7. Logout -- blacklists the refresh token on demand, not just on its next rotation"))
        resp = client.post("/api/auth/logout/", {"refresh": refresh}, format="json")
        self.stdout.write(f"  POST /api/auth/logout/ -> {resp.status_code}")
        assert resp.status_code == 205

        resp = client.post("/api/token/refresh/", {"refresh": refresh}, format="json")
        self.stdout.write(f"  POST /api/token/refresh/ with the logged-out token -> {resp.status_code}: {resp.data}")
        assert resp.status_code == 401

        self.stdout.write(self.style.SUCCESS(
            "\nConfirmed: register creates a real wallet, sensitive fields survive a PATCH unchanged, "
            "IsWalletOwner blocks update/destroy on someone else's wallet exactly like it blocks credit, "
            "and logout ends a session immediately instead of waiting for the token to expire on its own."
        ))

        if options["keep_data"]:
            self.stdout.write("\n--keep-data: left users api-demo-carol/api-demo-dave and dave's wallet in the DB.")
        else:
            for username in ("api-demo-carol", "api-demo-dave"):
                User.objects.filter(username=username).delete()
            Wallet.objects.filter(owner_id__in=["api-demo-carol", "api-demo-dave"]).delete()
