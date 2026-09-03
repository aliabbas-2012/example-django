from django.core.management.base import BaseCommand
from django.test import Client


class Command(BaseCommand):
    help = "Demonstrates middleware ordering and the request/response lifecycle, including a short-circuited chain."

    def handle(self, *args, **options):
        client = Client()

        self.stdout.write(self.style.MIGRATE_HEADING("1. Normal request -- full chain runs"))
        resp = client.get("/api/middleware-probe/")
        log = resp.wsgi_request.middleware_log
        for line in log:
            self.stdout.write(f"  {line}")
        self.stdout.write(f"  -> {resp.status_code}")
        assert resp.status_code == 200
        assert log == [
            "Outer: before view (request phase)",
            "ShortCircuit: before view (request phase)",
            "Inner: before view (request phase)",
            "View: handling request",
            "Inner: after view (response phase)",
            "ShortCircuit: after view (response phase)",
            "Outer: after view (response phase)",
        ]

        self.stdout.write(self.style.MIGRATE_HEADING("2. Same request with X-Block: 1 -- ShortCircuitMiddleware stops the chain"))
        resp = client.get("/api/middleware-probe/", HTTP_X_BLOCK="1")
        log = resp.wsgi_request.middleware_log
        for line in log:
            self.stdout.write(f"  {line}")
        self.stdout.write(f"  -> {resp.status_code}")
        assert resp.status_code == 403
        assert "View: handling request" not in log
        assert "Inner: before view (request phase)" not in log
        assert log == [
            "Outer: before view (request phase)",
            "ShortCircuit: before view (request phase)",
            "ShortCircuit: short-circuiting here -- view and InnerLifecycleMiddleware never run",
            "ShortCircuit: after view (response phase)",
            "Outer: after view (response phase)",
        ]

        self.stdout.write(self.style.SUCCESS(
            "\nConfirmed: request phase runs top-to-bottom through MIDDLEWARE, response phase "
            "runs bottom-to-top, and a short-circuit skips the view plus every middleware after "
            "it while everything before it still gets its response phase."
        ))
