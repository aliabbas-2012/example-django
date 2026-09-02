import logging

import redis
from celery import shared_task
from django.conf import settings
from django.db import IntegrityError, transaction

from payments.models import ProcessedEvent, Transaction, Wallet

logger = logging.getLogger(__name__)

redis_client = redis.Redis.from_url(settings.REDIS_URL)


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
    max_retries=5,
)
def process_payment_event(self, event_id: str, owner_id: str, amount: str) -> str:
    """
    Credits `owner_id`'s wallet by `amount`, exactly once, no matter how
    many times this task is delivered for the same `event_id`.

    Two problems solved here:

    1. Idempotency -- Celery (with acks_late=True) guarantees *at-least-once*
       delivery: a worker that dies after finishing the job but before
       acking it will have the task redelivered. `ProcessedEvent.event_id`
       is unique, so the second delivery's INSERT fails with
       IntegrityError and we bail out before touching the wallet again.

    2. Race conditions -- two deliveries of *different* events for the
       same wallet, processed by two different workers at the same time,
       must not stomp on each other's balance update (lost update
       problem). `select_for_update()` takes a row-level lock on the
       Wallet row for the duration of the transaction, so the second
       worker blocks until the first commits and then reads the
       up-to-date balance.
    """
    try:
        with transaction.atomic():
            # Claim the event first. If this raises, nothing below runs
            # and nothing was committed -- the atomic block rolls back.
            ProcessedEvent.objects.create(event_id=event_id)

            wallet = Wallet.objects.select_for_update().get(owner_id=owner_id)
            wallet.balance += amount
            wallet.save(update_fields=["balance"])
            Transaction.objects.create(wallet=wallet, event_id=event_id, amount=amount)

    except IntegrityError:
        logger.info("Event %s already processed, skipping", event_id)
        return f"duplicate:{event_id}"

    logger.info("Processed event %s for wallet %s (+%s)", event_id, owner_id, amount)
    return f"processed:{event_id}"


@shared_task(bind=True, max_retries=3)
def sync_with_external_gateway(self, owner_id: str) -> str:
    """
    Reconciles a wallet against an external payment gateway.

    This talks to a service outside our database, so a DB row lock can't
    protect it -- two workers could both pass the row lock check (there's
    nothing to lock yet), both call the external API, and double-charge
    or double-refund. A Redis distributed lock closes that gap: only one
    worker at a time may hold the lock for a given `owner_id`, across the
    whole fleet, not just within one process.
    """
    lock_key = f"lock:wallet-sync:{owner_id}"

    # blocking_timeout: how long to wait to acquire the lock before giving up.
    # timeout: the lock's own TTL, so a crashed worker doesn't hold it forever.
    lock = redis_client.lock(lock_key, timeout=10, blocking_timeout=5)

    acquired = lock.acquire(blocking=True)
    if not acquired:
        # Someone else is already syncing this wallet -- retry later
        # instead of racing them.
        raise self.retry(countdown=5)

    try:
        _call_external_gateway_and_reconcile(owner_id)
    finally:
        try:
            lock.release()
        except redis.exceptions.LockError:
            # Lock already expired (TTL) and/or released elsewhere -- fine.
            pass

    return f"synced:{owner_id}"


@shared_task
def check_endpoint_health(url: str) -> dict:
    """
    Pure I/O-bound work: the task spends almost all its time blocked on a
    socket, not on the CPU. This is the case for the `gevent`/`eventlet`
    worker pools -- each "worker" is a green thread (cooperative, single
    OS thread), so hundreds of them can be blocked on network I/O at once
    with a fraction of the memory/scheduling overhead of one OS process
    per worker. `prefork` (the default) is one OS process per worker,
    which is the right tradeoff for CPU-bound tasks (real parallelism,
    no GIL contention between processes) but wastes most of each
    process's time here just waiting on the network.

    Run this under both pools to see the difference:
        celery -A config worker -P prefork  --concurrency=4
        celery -A config worker -P gevent   --concurrency=50
    """
    import time

    import requests

    # CLOCK_MONOTONIC is system-wide on Linux, so `start` is directly
    # comparable across the separate worker processes -- this is what lets
    # the caller see whether calls landed in clusters (prefork) or all at
    # once (gevent).
    start = time.monotonic()
    resp = requests.get(url, timeout=15)
    return {"url": url, "status": resp.status_code, "elapsed": time.monotonic() - start, "started_at": start}


@shared_task
def count_primes_below(n: int) -> dict:
    """
    The CPU-bound counterpart to check_endpoint_health, for comparison.

    This is a tight Python loop -- no network, no disk, nothing to wait
    on. That's the opposite case from check_endpoint_health, and it's why
    the two pools trade places:

    - prefork: N worker processes are N real OS processes, so N of these
      loops genuinely run in parallel on N different CPU cores.

    - gevent: all its "workers" are green threads sharing ONE OS process.
      Its cooperative scheduler can only switch to another green thread
      at a blocking call (network, sleep, ...). A plain Python loop like
      this one never hits one, so it never yields -- gevent runs these
      one at a time to completion, no faster than concurrency=1.
    """
    import time

    start = time.monotonic()
    count = 0
    for candidate in range(2, n):
        is_prime = True
        for divisor in range(2, int(candidate**0.5) + 1):
            if candidate % divisor == 0:
                is_prime = False
                break
        if is_prime:
            count += 1
    return {"n": n, "primes_found": count, "elapsed": time.monotonic() - start, "started_at": start}


def _call_external_gateway_and_reconcile(owner_id: str) -> None:
    """
    Stand-in for the real HTTP call to the payment gateway. Sleeping here
    is what makes the race window in the demo below observable -- a real
    gateway call has the same shape (non-trivial latency, non-atomic
    with our DB), which is exactly why the lock is needed.
    """
    import time

    time.sleep(1)
