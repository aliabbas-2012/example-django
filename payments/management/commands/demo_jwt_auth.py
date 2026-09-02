from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from rest_framework.test import APIClient


class Command(BaseCommand):
    help = "Demonstrates SimpleJWT: obtain, use, rotate-on-refresh, and blacklist-after-rotation."

    def handle(self, *args, **options):
        User.objects.filter(username="jwt-demo").delete()
        User.objects.create_user(username="jwt-demo", password="demo-pass-123")
        client = APIClient()

        self.stdout.write(self.style.MIGRATE_HEADING("1. Unauthenticated request"))
        resp = client.get("/api/wallets/")
        self.stdout.write(f"  GET /api/wallets/ (no token) -> {resp.status_code}")
        assert resp.status_code == 401

        self.stdout.write(self.style.MIGRATE_HEADING("2. Obtain access + refresh tokens"))
        resp = client.post(
            "/api/token/", {"username": "jwt-demo", "password": "demo-pass-123"}, format="json"
        )
        access = resp.data["access"]
        refresh = resp.data["refresh"]
        self.stdout.write(f"  POST /api/token/ -> {resp.status_code}, got access + refresh")

        self.stdout.write(self.style.MIGRATE_HEADING("3. Authenticated request with the access token"))
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        resp = client.get("/api/wallets/")
        self.stdout.write(f"  GET /api/wallets/ (with access token) -> {resp.status_code}")
        assert resp.status_code == 200

        self.stdout.write(self.style.MIGRATE_HEADING("4. Refresh -> rotation issues a NEW refresh token"))
        client.credentials()  # refresh endpoint takes the refresh token in the body, not a bearer header
        resp = client.post("/api/token/refresh/", {"refresh": refresh}, format="json")
        new_access = resp.data["access"]
        new_refresh = resp.data["refresh"]
        self.stdout.write(f"  POST /api/token/refresh/ (1st use) -> {resp.status_code}, issued new access + new refresh")
        assert new_refresh != refresh

        self.stdout.write(self.style.MIGRATE_HEADING("5. Replay the OLD refresh token -- must be rejected"))
        resp = client.post("/api/token/refresh/", {"refresh": refresh}, format="json")
        self.stdout.write(f"  POST /api/token/refresh/ (REPLAY of used token) -> {resp.status_code}: {resp.data}")
        assert resp.status_code == 401

        self.stdout.write(self.style.MIGRATE_HEADING("6. The NEW refresh token still works"))
        resp = client.post("/api/token/refresh/", {"refresh": new_refresh}, format="json")
        self.stdout.write(f"  POST /api/token/refresh/ (new token, 1st use) -> {resp.status_code}")
        assert resp.status_code == 200

        self.stdout.write(self.style.SUCCESS("\nAll assertions passed: rotation + blacklist-after-rotation confirmed."))
