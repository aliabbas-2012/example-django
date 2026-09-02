import os
from datetime import datetime, timezone

import pymongo
from django.core.management.base import BaseCommand
from pymongo.errors import WriteError

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")

# Enforced server-side, at the collection level -- no document that fails
# this shape is ever written, regardless of which service or script wrote
# it. This is the guard against MongoDB silently becoming a schema-free
# dumping ground for whatever shape each ingestion service feels like
# sending.
TELEMETRY_SCHEMA = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["vehicle_id", "event_type", "payload", "recorded_at"],
        "properties": {
            "vehicle_id": {"bsonType": "string"},
            "event_type": {"bsonType": "string"},
            "payload": {"bsonType": "object"},
            "recorded_at": {"bsonType": "date"},
        },
    }
}


class Command(BaseCommand):
    help = "Demonstrates $jsonSchema validation and a TTL index on a raw telemetry collection."

    def handle(self, *args, **options):
        client = pymongo.MongoClient(MONGO_URL, serverSelectionTimeoutMS=5000)
        db = client["fleet_telemetry"]
        db.drop_collection("vehicle_events")
        db.create_collection("vehicle_events", validator=TELEMETRY_SCHEMA)
        collection = db["vehicle_events"]

        # 90-day retention on raw sensor telemetry -- Mongo deletes matching
        # documents itself once recorded_at is older than expireAfterSeconds;
        # nothing in the app has to remember to clean this up.
        collection.create_index("recorded_at", expireAfterSeconds=90 * 24 * 3600)

        self.stdout.write(self.style.MIGRATE_HEADING("1. Valid document"))
        result = collection.insert_one(
            {
                "vehicle_id": "veh-42",
                "event_type": "gps_ping",
                "payload": {"lat": 59.32, "lon": 18.06, "speed_kmh": 41.2},
                "recorded_at": datetime.now(timezone.utc),
            }
        )
        self.stdout.write(f"  inserted _id={result.inserted_id}")

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("2. Invalid document (missing required field) -- rejected by the schema, not application code"))
        try:
            collection.insert_one(
                {
                    "vehicle_id": "veh-43",
                    "event_type": "gps_ping",
                    # "payload" missing entirely
                    "recorded_at": datetime.now(timezone.utc),
                }
            )
            self.stdout.write(self.style.ERROR("  unexpectedly succeeded"))
        except WriteError as e:
            rule = e.details["errInfo"]["details"]["schemaRulesNotSatisfied"][0]
            missing = rule.get("missingProperties", [])
            self.stdout.write(f"  rejected: missing required properties {missing}")

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("3. TTL index in place"))
        for index in collection.list_indexes():
            if "expireAfterSeconds" in index:
                self.stdout.write(f"  {index['name']}: expireAfterSeconds={index['expireAfterSeconds']} (~90 days)")

        client.close()
