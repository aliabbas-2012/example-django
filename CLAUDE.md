# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A Django example project built to answer senior backend interview questions with real, runnable proof instead of documentation: N+1 queries, SimpleJWT rotation, drf-spectacular, Python 3.13 typing, Celery idempotency/race conditions, Celery worker pools, Postgres indexing, PostGIS, MongoDB, GCP Pub/Sub, Django signals, and the middleware request/response lifecycle. Every concept has a matching `demo_*` management command that seeds real data, exercises the real mechanism, and prints captured output — nothing is asserted without being run.

## Commands

Activate the venv first for anything below: `source .venv/bin/activate` (Python 3.13, installed via `uv` since this box only ships Python 3.10 system-wide).

```bash
python manage.py check
python manage.py makemigrations <app>
python manage.py migrate
python manage.py runserver
```

There is no test suite — verification is the `demo_*` commands themselves. On this machine everything, including PostGIS, runs on the host venv (see below) — Docker is not part of the normal workflow here.

## Two execution environments

This is the one thing to understand before touching settings, models, or the compose file.

Two *independent* env vars, both read in `config/settings.py`:

- `DJANGO_DB_HOST` — set it (directly, or via a host `.env`, see `.env.example`) to move off the default sqlite onto a real Postgres, anywhere reachable (a local `pg_dev`-style container, `docker compose`'s own containers, whatever). `USE_POSTGRES = bool(os.environ.get("DJANGO_DB_HOST"))`.
- `DJANGO_USE_GIS` — a separate, narrower flag that additionally loads `django.contrib.gis` + `fleet` into `INSTALLED_APPS` and switches the DB backend to `django.contrib.gis.db.backends.postgis`. `USE_POSTGIS = USE_POSTGRES and bool(os.environ.get("DJANGO_USE_GIS"))`. **Requires the GDAL/GEOS/PROJ *system* libraries to be importable via ctypes wherever this runs** — see below for what that means on this machine specifically.

**Host venv (what this machine actually uses for everything, Q1-Q14 including fleet/PostGIS)**: drop a `.env` (copy `.env.example`) with `DJANGO_DB_HOST` + creds to point at a real Postgres. `python-dotenv` loads `.env` at the top of `settings.py` and is a no-op if the file doesn't exist. `requirements-geo.txt` (`pymongo`, `google-cloud-pubsub`, `psycopg[binary]`) is installed into the host venv too — none of those three need GDAL. The host's local Redis (`redis://localhost:6379/15` — DB 15 specifically, to avoid colliding with unrelated keys already in DB 0) backs Celery.

GDAL/GEOS/PROJ themselves are **system** libraries (not pip-installable) — `django.contrib.gis` loads them via ctypes, so they must exist wherever `DJANGO_USE_GIS=1` runs. This machine has `sudo`, so they're installed directly on the host: `sudo apt-get install -y gdal-bin libgdal-dev libgeos-dev libproj-dev` (the exact packages the `Dockerfile` installs — see below). With those installed and `DJANGO_USE_GIS=1` set in `.env`, `fleet/` loads on the host venv exactly like it does in the container, and `demo_postgres_indexing`/`demo_postgis_queries` (Q7/Q8) run with a plain `python manage.py ...` — no Docker involved. **On a machine without `sudo`, this isn't possible** — that's the only reason the Docker path below exists at all.

**Docker (`docker compose up -d`)** — kept in the repo as a fallback for a machine *without* `sudo`/GDAL access, not part of this machine's normal workflow: `mongo`, `pubsub-emulator`, and `app`. There's no Postgres container in this compose file — `app`'s `DJANGO_DB_HOST` points at `host.docker.internal` (wired via `extra_hosts: host-gateway`), i.e. whatever Postgres/PostGIS is published on the *host's* port 5432. `app` sets `DJANGO_USE_GIS: "1"` and has GDAL baked in via `apt` in the `Dockerfile`, which is the *only* reason that image exists — a host that already has GDAL (like this one) has no need to build or run it. **Never import `django.contrib.gis` from code that also needs to run without `DJANGO_USE_GIS`/GDAL available** — it will fail to import there.

```bash
docker compose up -d                                              # start mongo, pubsub-emulator, app
docker compose exec app python manage.py <command>                 # anything needing PostGIS, on a no-sudo machine
docker compose down                                                 # add -v to also drop seeded data
```

If `docker` reports permission denied, the user's group membership needs a fresh login to take effect; until then prefix with `sg docker -c "..."`.

## Architecture

- **`config/`** — the one Django project. `settings.py` loads a host-only `.env` via `python-dotenv`, then branches `INSTALLED_APPS`/`DATABASES` on `USE_POSTGRES`/`USE_POSTGIS` (see "Two execution environments" above). `celery.py` is the Celery app entrypoint (`config.celery.app`), imported in `config/__init__.py` so `@shared_task` works app-wide.
- **`payments/`** — the always-loaded app. Core models: `Wallet` (`balance` is mutated directly, under a row lock, only inside `tasks.py:process_payment_event`; `txn_count` is a separate field mutated only by the `post_save` signal in `signals.py` — kept apart on purpose so the signal demo can't double-credit the idempotency demo's balance), `ProcessedEvent` (idempotency ledger — unique `event_id` is what makes `IntegrityError` the redelivery-detection signal), `Transaction` (ledger rows, FK to `Wallet`, exists specifically to demonstrate N+1 in both FK directions). `tasks.py` holds every Celery task; each one's docstring explains the concept it demonstrates rather than just what it does — read those before modifying task behavior. `webhook_schema.py` is a self-contained Python 3.13 typing demo (`TypeIs` + `ReadOnly` `TypedDict`) consumed by `GatewayWebhookView`. `signals.py` is connected once, from `apps.py:PaymentsConfig.ready()` (Django's documented hook for this — not from a bare module-level import). `middleware.py` holds three logging-only middleware classes (`OuterLifecycleMiddleware`, `ShortCircuitMiddleware`, `InnerLifecycleMiddleware`, wired into `config/settings.py:MIDDLEWARE` in that order) that exist solely so `demo_middleware_lifecycle` can capture the real request/response call order, including a short-circuited chain, off `request.middleware_log` rather than a module-level list. `permissions.py` holds `IsWalletOwner`, an object-level permission — deliberately separate from the project-wide `IsAuthenticated` default, so `demo_drf_internals`/`demo_auth_api` can produce a genuine 401 (no token) and a genuine 403 (valid token, wrong wallet) from two different code paths rather than describing the difference.

`WalletViewSet` is a full `ModelViewSet` (not read-only): `get_permissions()` requires `IsWalletOwner` in addition to `IsAuthenticated` for `update`/`partial_update`/`destroy`/`credit` only — centralized there rather than split across each `@action`'s own `permission_classes` kwarg, since only one of the two can actually be in effect per action. `perform_create` always sets `owner_id` from the authenticated user (never from the request body) and turns the resulting `IntegrityError` on a second wallet into a clean 400 instead of a raw 500. `WalletSerializer` marks `owner_id`/`balance`/`txn_count` all read-only, so a `PATCH` trying to hand-set a balance is silently a no-op — proven, not just asserted, in `demo_auth_api`. `RegisterView` creates the `User` and its `Wallet` in one call; `MeView` returns both together; `LogoutView` blacklists a refresh token on demand (SimpleJWT's own rotation in Q2 only blacklists on the *next* rotation, not immediately).
- **`fleet/`** — PostGIS-only app, loaded conditionally (see above). `VehiclePosition.status` is deliberately left unindexed at the model level so `demo_postgres_indexing` has a real "before" state to show, not a staged one — don't add `db_index` to it.
- **`payments/management/commands/` and `fleet/management/commands/`** — one `demo_*` command per interview question. Each is a complete, idempotent, rerunnable proof: it seeds/clears its own data, runs the real mechanism, and prints real captured output (query counts via `CaptureQueriesContext`, raw `EXPLAIN` output, actual HTTP status codes, actual redelivered Pub/Sub `message_id`s). When adding a new demo, follow this pattern — seed inside the command, assert nothing that wasn't actually observed. `demo_django_signals`, `demo_drf_internals`, and `demo_auth_api` additionally accept `--keep-data` to skip their final cleanup, for when you actually want to inspect the seeded rows instead of just reading stdout.
- **`postman/`** — a Postman collection (`example-django-auth-api.postman_collection.json`) exercising the register/login/me/refresh/logout + wallet CRUD flow as real HTTP requests against `python manage.py runserver`, no Docker `app` container involved. Verified with `npx newman run ...` — see `postman/README.md` for the run order and why it matters (folder 3's 403 checks need folder 2 to not have already deleted the wallet, hence the dedicated cleanup folder at the end).
- **Redis is reused across concepts on purpose**: the same `redis://localhost:6379/15` instance backs the Celery broker (Q5/Q6), the distributed lock in `sync_with_external_gateway` (Q5), and the message-dedup cache in `demo_pubsub_delivery` (Q10) — this mirrors how a real system would reuse one Redis instance for multiple concerns rather than standing up separate ones per feature.
- **`requirements.txt`** is what the host venv installs by default; **`requirements-geo.txt`** (pymongo, google-cloud-pubsub, psycopg[binary]) is always installed *in addition* inside the Docker `app` image (see `Dockerfile`), and can also be installed into the host venv on demand to unlock Q9/Q10/real-Postgres-on-host — none of those three packages need GDAL themselves. The one thing that's genuinely container-only is `django.contrib.gis` (Q7/Q8's `fleet/`), because *it* needs the GDAL/GEOS/PROJ system libraries installed via `apt` in the `Dockerfile`, which pip can't provide. Keep that system dependency (not the geo *requirements file*) out of anything meant to import on the host.
