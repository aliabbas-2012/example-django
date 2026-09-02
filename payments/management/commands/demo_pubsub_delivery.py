import os
import time

import redis
from django.core.management.base import BaseCommand
from google.api_core.exceptions import AlreadyExists
from google.cloud import pubsub_v1

os.environ.setdefault("PUBSUB_EMULATOR_HOST", "localhost:8085")
PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "payments-demo")
TOPIC = "vehicle-events"
DLQ_TOPIC = "vehicle-events-dead-letter"
SUBSCRIPTION = "vehicle-events-sub"
ACK_DEADLINE = 5  # seconds -- short on purpose, so redelivery is fast to observe

redis_client = redis.Redis.from_url("redis://localhost:6379/15")


class Command(BaseCommand):
    help = "Demonstrates Pub/Sub at-least-once redelivery, Redis-backed dedup, and a manual dead-letter pattern."

    def handle(self, *args, **options):
        publisher = pubsub_v1.PublisherClient()
        subscriber = pubsub_v1.SubscriberClient()

        topic_path = publisher.topic_path(PROJECT, TOPIC)
        dlq_topic_path = publisher.topic_path(PROJECT, DLQ_TOPIC)
        sub_path = subscriber.subscription_path(PROJECT, SUBSCRIPTION)

        for path, creator in [
            (topic_path, lambda: publisher.create_topic(request={"name": topic_path})),
            (dlq_topic_path, lambda: publisher.create_topic(request={"name": dlq_topic_path})),
        ]:
            try:
                creator()
            except AlreadyExists:
                pass
        try:
            subscriber.create_subscription(
                request={"name": sub_path, "topic": topic_path, "ack_deadline_seconds": ACK_DEADLINE}
            )
        except AlreadyExists:
            pass

        self.stdout.write(self.style.MIGRATE_HEADING("1. Publish one message"))
        future = publisher.publish(topic_path, b'{"vehicle_id": "veh-1", "event": "engine_on"}')
        message_id = future.result()
        self.stdout.write(f"  published message_id={message_id}")

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("2. Pull it, but DON'T ack (simulates a worker crashing mid-process)"))
        resp = subscriber.pull(request={"subscription": sub_path, "max_messages": 1})
        first_received = resp.received_messages[0]
        self.stdout.write(f"  received message_id={first_received.message.message_id}, ack_id withheld")

        self.stdout.write(f"  sleeping past the {ACK_DEADLINE}s ack deadline so Pub/Sub redelivers it...")
        time.sleep(ACK_DEADLINE + 2)

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("3. Pull again -- Pub/Sub guarantees at-least-once, so it's redelivered"))
        resp = subscriber.pull(request={"subscription": sub_path, "max_messages": 1})
        second_received = resp.received_messages[0]
        redelivered = second_received.message.message_id == first_received.message.message_id
        self.stdout.write(f"  received message_id={second_received.message.message_id}  (same message: {redelivered})")
        assert redelivered

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("4. Idempotent processing via a Redis dedup cache"))
        dedup_key = f"pubsub:seen:{second_received.message.message_id}"
        already_seen = redis_client.exists(dedup_key)
        self.stdout.write(f"  already processed before? {bool(already_seen)}")
        if already_seen:
            self.stdout.write("  -> skip reprocessing, ack and move on")
        else:
            self.stdout.write("  -> process it for real, then mark seen")
            redis_client.set(dedup_key, "1", ex=86400)
        subscriber.acknowledge(request={"subscription": sub_path, "ack_ids": [second_received.ack_id]})
        self.stdout.write("  acked")

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("5. Dead-letter pattern: a 'poison' message that keeps failing"))
        future = publisher.publish(topic_path, b'{"vehicle_id": "veh-666", "event": "corrupt_payload"}')
        poison_id = future.result()
        self.stdout.write(f"  published poison message_id={poison_id}")

        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            resp = subscriber.pull(request={"subscription": sub_path, "max_messages": 1})
            msg = resp.received_messages[0]
            self.stdout.write(f"  attempt {attempt}: processing raises -- nacking (modify_ack_deadline=0)")
            subscriber.modify_ack_deadline(
                request={"subscription": sub_path, "ack_ids": [msg.ack_id], "ack_deadline_seconds": 0}
            )
            if attempt == max_attempts:
                self.stdout.write(f"  max_attempts ({max_attempts}) reached -- forwarding to {DLQ_TOPIC} and acking the original")
                dlq_future = publisher.publish(dlq_topic_path, msg.message.data)
                dlq_future.result()  # block until the DLQ publish is actually confirmed
                subscriber.acknowledge(request={"subscription": sub_path, "ack_ids": [msg.ack_id]})

        subscriber.close()
        self.stdout.write(self.style.SUCCESS("\nAll assertions passed."))
