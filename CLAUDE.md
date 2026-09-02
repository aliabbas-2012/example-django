# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A Django example project built to answer ten senior backend interview questions with real, runnable proof instead of documentation: N+1 queries, SimpleJWT rotation, drf-spectacular, Python 3.13 typing, Celery idempotency/race conditions, Celery worker pools, Postgres indexing, PostGIS, MongoDB, and GCP Pub/Sub. Every concept has a matching `demo_*` management command that seeds real data, exercises the real mechanism, and prints captured output — nothing is asserted without being run.

## Commands

Activate the venv first for anything below: `source .venv/bin/activate` (Python 3.13, installed via `uv` since this box only ships Python 3.10 system-wide).

```bash
python manage.py check
python manage.py makemigrations <app>
python manage.py migrate
python manage.py runserver
```

There is no test suite — verification is the `demo_*` commands themselves (see "Two execution environments" below for which ones need Docker).

## Two execution environments

This is the one thing to understand before touching settings, models, or the compose file.

**Host venv** (`config/settings.py` with `DJANGO_DB_HOST` unset): SQLite, the host's local Redis (`redis://localhost:6379/15` — DB 15 specifically, to avoid colliding with unrelated keys already in DB 0 on this machine). Covers the Django/Celery/DRF/JWT concepts (Q1, Q2, Q3, Q5, Q6) and the Mongo/Pub/Sub demos (Q9, Q10), whose Python clients (`pymongo`, `google-cloud-pubsub`) are pure-Python and can reach the Docker containers' published ports directly.

**Docker (`docker compose up -d`)**: a `db` (postgis/postgis), `mongo`, `pubsub-emulator`, and `app` service. The `app` service exists *only* because `django.contrib.gis` needs GDAL/GEOS client libraries to even import, and those are only installed inside that container (via `apt` in the `Dockerfile` — not on the host, which has no `sudo`-free way to get them). `fleet/` (PostGIS models: `DepotBay`, `VehiclePosition`) is gated behind `USE_POSTGIS = bool(os.environ.get("DJANGO_DB_HOST"))` in settings — it's only added to `INSTALLED_APPS`, and the DB backend only switches to `django.contrib.gis.db.backends.postgis`, when that env var is set, which happens only inside the `app` container. **Never import `django.contrib.gis` from code that also needs to run on the host venv** — it will fail to import there.

```bash
docker compose up -d                                              # start db, mongo, pubsub-emulator, app
docker compose exec app python manage.py <command>                 # anything needing PostGIS
docker compose down                                                 # add -v to also drop seeded data
```

If `docker` reports permission denied, the user's group membership needs a fresh login to take effect; until then prefix with `sg docker -c "..."`.

## Architecture

- **`config/`** — the one Django project. `settings.py` branches on `USE_POSTGIS` for both `INSTALLED_APPS` and `DATABASES`. `celery.py` is the Celery app entrypoint (`config.celery.app`), imported in `config/__init__.py` so `@shared_task` works app-wide.
- **`payments/`** — the always-loaded app. Core models: `Wallet`, `ProcessedEvent` (idempotency ledger — unique `event_id` is what makes `IntegrityError` the redelivery-detection signal), `Transaction` (ledger rows, FK to `Wallet`, exists specifically to demonstrate N+1 in both FK directions). `tasks.py` holds every Celery task; each one's docstring explains the concept it demonstrates rather than just what it does — read those before modifying task behavior. `webhook_schema.py` is a self-contained Python 3.13 typing demo (`TypeIs` + `ReadOnly` `TypedDict`) consumed by `GatewayWebhookView`.
- **`fleet/`** — PostGIS-only app, loaded conditionally (see above). `VehiclePosition.status` is deliberately left unindexed at the model level so `demo_postgres_indexing` has a real "before" state to show, not a staged one — don't add `db_index` to it.
- **`payments/management/commands/` and `fleet/management/commands/`** — one `demo_*` command per interview question. Each is a complete, idempotent, rerunnable proof: it seeds/clears its own data, runs the real mechanism, and prints real captured output (query counts via `CaptureQueriesContext`, raw `EXPLAIN` output, actual HTTP status codes, actual redelivered Pub/Sub `message_id`s). When adding a new demo, follow this pattern — seed inside the command, assert nothing that wasn't actually observed.
- **Redis is reused across concepts on purpose**: the same `redis://localhost:6379/15` instance backs the Celery broker (Q5/Q6), the distributed lock in `sync_with_external_gateway` (Q5), and the message-dedup cache in `demo_pubsub_delivery` (Q10) — this mirrors how a real system would reuse one Redis instance for multiple concerns rather than standing up separate ones per feature.
- **`requirements.txt`** is what the host venv installs; **`requirements-geo.txt`** (pymongo, google-cloud-pubsub, psycopg) is installed *in addition* only inside the Docker `app` image (see `Dockerfile`) — keep host-incompatible or GDAL-adjacent dependencies out of `requirements.txt`.
