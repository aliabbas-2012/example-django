import random

from django.contrib.gis.geos import Point
from django.core.management.base import BaseCommand
from django.db import connection

from fleet.models import DepotBay, VehiclePosition

# A real depot: Stockholm. Vehicles are scattered around it, some inside
# a 50m radius, most far outside it.
DEPOT_LON, DEPOT_LAT = 18.06, 59.32
N_VEHICLES = 50_000


class Command(BaseCommand):
    help = "Demonstrates GEOMETRY vs GEOGRAPHY distance semantics, and ST_DWithin vs ST_Distance index usage."

    def handle(self, *args, **options):
        DepotBay.objects.all().delete()
        depot = DepotBay.objects.create(name="stockholm-main", location=Point(DEPOT_LON, DEPOT_LAT))

        # Always own the whole table and reseed -- this command needs
        # points scattered around the depot, which is a different shape
        # of data than demo_postgres_indexing seeds into the same table.
        self.stdout.write(f"Seeding {N_VEHICLES} vehicle positions scattered around the depot...")
        VehiclePosition.objects.all().delete()
        batch = []
        # A handful of vehicles are placed within 50m on purpose so the
        # ST_DWithin query below has real matches, not zero.
        for i in range(200):
            offset_deg = random.uniform(0, 0.0003)  # up to ~30m at this latitude
            angle = random.uniform(0, 6.28318)
            lon = DEPOT_LON + offset_deg * 1.4  # rough deg-per-meter correction at 59N
            lat = DEPOT_LAT + offset_deg
            batch.append(VehiclePosition(vehicle_id=f"veh-near-{i}", status="en_route", location=f"POINT({lon} {lat})"))
        for i in range(N_VEHICLES - 200):
            # Scattered across ~11km box around the depot -- effectively
            # all far outside the 50m radius.
            lon = DEPOT_LON + random.uniform(-0.05, 0.05)
            lat = DEPOT_LAT + random.uniform(-0.05, 0.05)
            batch.append(VehiclePosition(vehicle_id=f"veh-{i}", status="en_route", location=f"POINT({lon} {lat})"))
            if len(batch) >= 5000:
                VehiclePosition.objects.bulk_create(batch)
                batch = []
        if batch:
            VehiclePosition.objects.bulk_create(batch)

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("1. GEOMETRY vs GEOGRAPHY: same points, different distance semantics"))
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    ST_Distance(location::geometry, ST_SetSRID(ST_MakePoint(%s, %s), 4326)) AS geometry_distance,
                    ST_Distance(location, ST_MakePoint(%s, %s)::geography) AS geography_distance_meters
                FROM fleet_vehicleposition
                ORDER BY id LIMIT 3
                """,
                [DEPOT_LON, DEPOT_LAT, DEPOT_LON, DEPOT_LAT],
            )
            for geom_dist, geog_dist in cursor.fetchall():
                self.stdout.write(
                    f"  geometry: {geom_dist:.6f} (raw degrees, meaningless as a distance) "
                    f"  |  geography: {geog_dist:.1f} m (real spheroidal distance)"
                )

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("2. ST_DWithin (uses the GiST index) vs ST_Distance < N (can't)"))
        with connection.cursor() as cursor:
            cursor.execute("CREATE INDEX IF NOT EXISTS fleet_vehicleposition_location_gix ON fleet_vehicleposition USING GIST (location)")

            cursor.execute(
                "EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM fleet_vehicleposition "
                "WHERE ST_DWithin(location, ST_MakePoint(%s, %s)::geography, 50)",
                [DEPOT_LON, DEPOT_LAT],
            )
            self.stdout.write("  ST_DWithin plan:")
            for (row,) in cursor.fetchall():
                self.stdout.write(f"    {row}")

            cursor.execute(
                "EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM fleet_vehicleposition "
                "WHERE ST_Distance(location, ST_MakePoint(%s, %s)::geography) < 50",
                [DEPOT_LON, DEPOT_LAT],
            )
            self.stdout.write("  ST_Distance < 50 plan:")
            for (row,) in cursor.fetchall():
                self.stdout.write(f"    {row}")

        matched = VehiclePosition.objects.raw(
            "SELECT id, vehicle_id FROM fleet_vehicleposition "
            "WHERE ST_DWithin(location, ST_MakePoint(%s, %s)::geography, 50) LIMIT 5",
            [DEPOT_LON, DEPOT_LAT],
        )
        self.stdout.write(f"\n  sample vehicles within 50m of {depot.name}: {[v.vehicle_id for v in matched]}")
