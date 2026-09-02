import random

from django.core.management.base import BaseCommand
from django.db import connection

from fleet.models import VehiclePosition

N_ROWS = 200_000
STATUSES = ["idle", "en_route", "loading", "maintenance"]
QUERY = "SELECT * FROM fleet_vehicleposition WHERE status = 'maintenance'"


class Command(BaseCommand):
    help = "Seeds 200k rows and runs a real EXPLAIN (ANALYZE, BUFFERS) before and after adding a B-Tree index."

    def handle(self, *args, **options):
        with connection.cursor() as cursor:
            cursor.execute("DROP INDEX IF EXISTS fleet_vehicleposition_status_idx")

        if VehiclePosition.objects.count() < N_ROWS:
            self.stdout.write(f"Seeding {N_ROWS} rows (one-time, cached for reruns)...")
            VehiclePosition.objects.all().delete()
            batch = []
            for i in range(N_ROWS):
                batch.append(
                    VehiclePosition(
                        vehicle_id=f"veh-{i % 500}",
                        status=random.choice(STATUSES),
                        location="POINT(18.06 59.32)",
                    )
                )
                if len(batch) == 5000:
                    VehiclePosition.objects.bulk_create(batch)
                    batch = []
            if batch:
                VehiclePosition.objects.bulk_create(batch)

        self.stdout.write(self.style.MIGRATE_HEADING("BEFORE index: EXPLAIN (ANALYZE, BUFFERS)"))
        self._explain()

        with connection.cursor() as cursor:
            cursor.execute("CREATE INDEX fleet_vehicleposition_status_idx ON fleet_vehicleposition (status)")
            cursor.execute("ANALYZE fleet_vehicleposition")

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("AFTER index + ANALYZE: EXPLAIN (ANALYZE, BUFFERS)"))
        self._explain()

    def _explain(self):
        with connection.cursor() as cursor:
            cursor.execute(f"EXPLAIN (ANALYZE, BUFFERS) {QUERY}")
            for row in cursor.fetchall():
                self.stdout.write(f"  {row[0]}")
