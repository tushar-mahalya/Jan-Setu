# Jan Setu

FastAPI backend for Jan Setu WhatsApp Business send/receive flows.

## Features

- WhatsApp Business send/receive flows with an auto-reply conversation engine
- A React + TypeScript citizen web portal with reverse-OTP WhatsApp-based login
- An LLM-driven complaint pipeline: Sarvam speech-to-text, OpenRouter-based
  classification, and image-match checking via free models
- A dedup window for non-priority complaints (priority categories skip it)
- Department dispatch via a mock API or SMTP (Mailpit locally)

## What Runs Locally

- `api`: FastAPI app on `http://localhost:8000`
- `postgres`: local PostgreSQL database on port `5432`
- `mailpit`: local-only SMTP inbox with a web UI on `http://localhost:8025`,
  used when `DISPATCHER=smtp`
- `tunnel`: optional Cloudflare tunnel for WhatsApp webhook testing

## Docker Profiles

| Profile | Purpose | Runs in Docker |
| --- | --- | --- |
| `dev` | Daily development and WhatsApp webhook testing | PostgreSQL, `worker-dev`, Mailpit, Cloudflare tunnel |
| `prod` | Local production-like demo only | PostgreSQL, API, worker, frontend/Nginx, Mailpit |

`prod` is **not** an Azure deployment recipe. Azure replaces local PostgreSQL and
Mailpit with managed PostgreSQL plus a real email delivery service. The temporary
dev tunnel is intentionally excluded from `prod`.

## Run Locally — Full Application

Use this path to run the database, API, worker, frontend, and local email inbox together.

### Prerequisites

Install once:

- Docker Desktop, running
- Git

For the Docker workflow below, Python, `uv`, and Node.js are **not** required on the host.

### Start everything
```sh
git clone git@github.com:21f1005763/MAY2026-Team-050.git
cd MAY2026-Team-050
cp .env.example .env
docker compose --profile prod up -d --build
docker compose exec -T api uv run alembic upgrade head
```

Wait until all services are healthy:

```sh
docker compose --profile prod ps
```

Open these URLs:

| Service | URL |
| --- | --- |
| Citizen web app | http://localhost:8080 |
| API documentation | http://localhost:8000/docs |
| Mailpit email inbox | http://localhost:8025 |
| API health check | http://localhost:8000/health |

The frontend proxies `/api` and `/auth` to the API container. Use
`http://localhost:8080` for the complete browser flow; do not use the Vite
port for this Docker workflow.

### Stop, restart, or reset

```sh
# Stop containers; keep database and uploaded files.
docker compose --profile prod down

# Start previous images again.
docker compose --profile prod up -d

# Follow logs for every service.
docker compose --profile prod logs -f

# Remove local database and uploaded files. This deletes all local data.
docker compose --profile prod down -v
```

After a reset, start services and re-run migrations:

```sh
docker compose --profile prod up -d --build
docker compose exec -T api uv run alembic upgrade head
```

### Browser end-to-end checklist

1. Open http://localhost:8080.
2. Open **Sign in** and request a verification code with a phone number.
3. Send displayed code to the configured Jan Setu WhatsApp Business number.
4. After verification, create a complaint: select location, add description or voice clip, optionally attach photo, review, and submit.
5. Confirm complaint appears in dashboard and open its detail page.
6. For SMTP dispatch testing, set `DISPATCHER=smtp` in `.env`, restart the API and worker, then inspect sent messages in Mailpit at http://localhost:8025.

> Local application startup works with `.env.example`. Actual WhatsApp sign-in
> requires valid Meta credentials plus `PUBLIC_WA_NUMBER`; see
> [WhatsApp Webhook Testing](#whatsapp-webhook-testing). Without those values,
> the portal and API run normally but a browser login cannot complete.

## Run Locally — Development Workflow

This is the only workflow needed for everyday development:

| Runs in Docker | Runs on your machine |
| --- | --- |
| PostgreSQL, background worker, Mailpit email inbox | FastAPI API, Vite frontend |

You get Docker-managed background services while retaining FastAPI reload/debugging
and Vite hot module reload. **Do not run `uv run jan-setu-worker` locally.**

### Prerequisites

- Python 3.11+
- Node.js 20+
- Docker Desktop
- `uv`: <https://docs.astral.sh/uv/getting-started/installation/>

### One-time setup

```sh
cd MAY2026-Team-050
cp .env.example .env
sh scripts/setup-dev.sh
```

`setup-dev.sh` is the only supported setup path — it installs dependencies and
the git hooks. Running `uv sync` alone leaves the hooks uninstalled.

### Start the stack

Run these commands in order:

```sh
# 1. Docker: PostgreSQL + worker + Mailpit.
docker compose --profile dev up -d --build

# 2. Apply database schema to Docker PostgreSQL.
uv run alembic upgrade head
```

Then use exactly two terminals:

```sh
# Terminal 1 — FastAPI API with local code reload
uv run jan-setu-api
```

```sh
# Terminal 2 — React/Vite frontend with hot reload
npm --prefix frontend run dev
```

Open:

| What | URL |
| --- | --- |
| Web application | http://localhost:5173 |
| FastAPI docs | http://localhost:8000/docs |
| Mailpit inbox | http://localhost:8025 |

Vite proxies `/api` and `/auth` to the locally running FastAPI server. The
Docker worker talks to that same host API through `host.docker.internal` and
uses the Docker PostgreSQL database and Mailpit inbox.

### Configure the WhatsApp webhook tunnel

After FastAPI is running, get the temporary public URL:

```sh
docker compose --profile dev logs -f tunnel
```

Copy the printed `https://...trycloudflare.com` URL into Meta WhatsApp Developer
Portal as:

```text
https://YOUR-TRY-CLOUDFLARE-URL/whatsapp/webhook
```

Use `WHATSAPP_VERIFY_TOKEN` from `.env` as Meta's verify token. The URL changes
when the tunnel container is recreated. Do not use this temporary tunnel for
Azure production.

### Demo municipal dispatch

The project supports both a dummy municipal API path and visible dummy email:

```env
# .env: simulated municipal API response
DISPATCHER=mock_api

# .env: fake department email visible in Mailpit
DISPATCHER=smtp
SMTP_HOST=localhost
SMTP_PORT=1025
SMTP_FROM=no-reply@jan-setu.local
```

After changing `.env`, restart FastAPI and the Docker worker:

```sh
docker compose --profile dev restart worker-dev
```

With `DISPATCHER=smtp`, submitted/dispatchable complaints appear in Mailpit at
http://localhost:8025. Mailpit is a local demo inbox, never an Azure production
mail service.

### Daily commands

```sh
# Start background services after a reboot.
docker compose --profile dev up -d

# Watch worker logs.
docker compose --profile dev logs -f worker-dev

# Watch all background-service logs.
docker compose --profile dev logs -f

# Stop background services but keep database/uploads.
docker compose --profile dev down

# Delete all local database/uploads. This cannot be undone.
docker compose --profile dev down -v
```

Mailpit is local-only. It runs natively on Apple Silicon and exposes SMTP on
port `1025` plus its inbox on port `8025`; it is never part of Azure production
deployment.

The app builds its host-local PostgreSQL connection from `POSTGRES_HOST`,
`POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, and `POSTGRES_PASSWORD` in
`.env`. Set `DATABASE_URL` only when a deployment platform supplies one full
connection URL.

Re-run the setup helper after changing dependencies or hook configuration:

```sh
sh scripts/setup-dev.sh
```

## Verify Everything Works

In a second terminal:

```sh
uv run pytest
uv run ruff check .
```

Test the webhook verification endpoint:

```sh
curl "http://localhost:8000/whatsapp/webhook?hub.mode=subscribe&hub.verify_token=dev_verify_token&hub.challenge=hello"
```

Expected response:

```text
hello
```

## Daily Development Commands

Start the database:

```sh
docker compose up -d postgres
```

Run migrations:

```sh
uv run alembic upgrade head
```

Start the API:

```sh
uv run jan-setu-api
```

Run checks:

```sh
uv run pytest
uv run ruff check .
uv run pre-commit run --all-files
```

Stop local containers:

```sh
docker compose down
```

If you change local Postgres credentials after a database volume already exists, recreate the dev volume:

```sh
docker compose down -v
docker compose up -d postgres
uv run alembic upgrade head
```

## Run Everything In Docker — Local Production-Like Demo

Use the `prod` profile only to demonstrate the fully containerized stack:

```sh
docker compose --profile prod up -d --build
docker compose exec -T api uv run alembic upgrade head
```

Open the portal at http://localhost:8080, API docs at http://localhost:8000/docs,
and Mailpit at http://localhost:8025. Do not run host FastAPI or Vite at the
same time as this profile.

## Local End-to-End Verification

Use the `dev` workflow for normal end-to-end verification:

```sh
docker compose --profile dev up -d --build
uv run alembic upgrade head
uv run pytest -q
uv run ruff check .
```

Then run FastAPI and Vite in the two terminals described above. With
`DISPATCHER=smtp`, dispatch emails appear in Mailpit at http://localhost:8025.
Do not run a host worker; `worker-dev` already handles background processing.

## Database Migrations

The schema is managed by Alembic. Models live in `src/jan_setu/models.py`, and
`Base.metadata` uses a naming convention so constraint and index names are
deterministic across environments.

Apply the latest schema:

```sh
uv run alembic upgrade head
```

After changing a model, generate a migration and review it before committing:

```sh
uv run alembic revision --autogenerate -m "describe your change"
```

Autogenerated files use single quotes; the `ruff format` pre-commit hook
reformats them on commit (or run `uv run ruff format migrations/versions/<file>.py`).
Always review the generated `upgrade()` / `downgrade()` — autogenerate is a
starting point, not a guarantee.

Detect un-migrated model changes (this also runs in CI):

```sh
uv run alembic check
```

## WhatsApp Webhook Testing

Set these values in `.env` when testing with Meta:

```text
WHATSAPP_VERIFY_TOKEN=dev_verify_token
WHATSAPP_APP_SECRET=
WHATSAPP_ACCESS_TOKEN=
WHATSAPP_PHONE_NUMBER_ID=
WHATSAPP_GRAPH_API_VERSION=v20.0
```

Do not commit `.env` or real tokens.

With the API running on port `8000`, the `dev` profile already starts a temporary Cloudflare tunnel. Print its URL with:

```sh
docker compose --profile dev logs -f tunnel
```

Use the printed URL in Meta with this path:

```text
https://YOUR-TEMP-URL.trycloudflare.com/whatsapp/webhook
```

Use the same verify token in Meta that you set as `WHATSAPP_VERIFY_TOKEN`.

## How Inbound Messages Are Handled

Incoming webhooks are acknowledged immediately and processed off the request path:

1. The Meta signature is verified, the raw event is stored, and `200` is returned
   right away so slow processing never triggers Meta retries.
2. A background task parses and stores each message — text, media
   (`media_id` / `media_mime_type`), and location (`location_*`) are captured.
3. `src/jan_setu/processing.py` is the seam where the complaint pipeline
   (classification, routing, replies) plugs in.

The Docker worker adds durability: it polls for any event left unprocessed (a
background task that failed or never ran) and drains it in batches, controlled
by `WORKER_POLL_SECONDS` and `WORKER_BATCH_SIZE`. Re-processing is idempotent.
`worker-dev` runs in the `dev` profile beside host FastAPI; `worker` runs in the
`prod` profile beside containerized API. Each also sweeps persisted outbound
replies that were not yet sent.

## Auto-Reply Conversation Engine

When `AUTO_REPLY_ENABLED=true`, inbound messages drive a guided dialog: greet →
request the citizen's location (native WhatsApp "Send location" button) →
reverse-geocode the coordinates → confirm the address with Yes/No buttons → ask
the citizen to describe their issue. State lives in the `conversations` table;
each inbound message is consumed exactly once (`fsm_message_consumptions`), and
replies are persisted before sending so a crash never drops or duplicates them.

### Reverse geocoding (production note)

Reverse geocoding is pluggable (`GEOCODER_PROVIDER`). The default points at the
**public Nominatim endpoint, which is DEV-ONLY**: the OpenStreetMap usage policy
caps it at 1 request/second and forbids app/bulk traffic. For production set
`NOMINATIM_BASE_URL` to a self-hosted Nominatim/Photon (an India OSM extract) or a
paid provider, and keep the identifying `NOMINATIM_USER_AGENT`. Results are cached
in `geocode_cache` and calls are globally throttled via `external_rate_limits`.

## JWT secret configuration

`JWT_SECRET` must be at least 32 bytes. Development and test use the clearly
local-only value in `.env.example`; staging and production reject that value and
fail during settings construction/startup rather than starting with an unsafe
secret. Generate a unique random secret for each deployment and store it in the
platform secret manager. Rotating it immediately invalidates existing access
tokens (and users must sign in again); plan refresh-token/session impact accordingly.
Never log or commit the secret, and do not replace an existing active `.env`
without deliberately rotating credentials.

## API Authentication

The management API (`/v1/...`) is open in development. Set `API_KEY` to require
an `X-API-Key` header on those endpoints; it is mandatory outside development.

```text
API_KEY=your-strong-key
```

Send it with each request:

```sh
curl http://localhost:8000/v1/contacts -H "X-API-Key: your-strong-key"
```

## Useful API Calls

List contacts:

```sh
curl http://localhost:8000/v1/contacts
```

List messages:

```sh
curl http://localhost:8000/v1/messages
```

Send a WhatsApp text message:

```sh
curl -X POST http://localhost:8000/v1/messages/text \
  -H "Content-Type: application/json" \
  -d '{"to":"911234567890","body":"Hello from Jan Setu"}'
```

## CI

GitHub Actions runs three jobs in parallel on pull requests and pushes to `main`
(see `.github/workflows/ci.yml`):

- **lint** — `pre-commit` (Ruff lint + format and hygiene hooks)
- **test** — the `pytest` suite
- **migrations** — applies migrations to a clean Postgres and runs `alembic check`
  to catch model/migration drift

A `ci-success` job aggregates them. Require the **`CI success`** status check in
branch protection so every check must pass before a PR can merge.

## Live Dev Deployment (OCI)

`main` auto-deploys to a live dev instance on an Oracle Cloud "Always Free"
Ampere VM. `.github/workflows/deploy-dev.yml` triggers once `ci.yml` passes on
`main`, SSHes in, and runs:

```sh
git fetch origin main && git reset --hard origin/main
docker compose up -d --build api worker frontend postgres
docker compose exec -T api uv run alembic upgrade head
```

`mailpit` and `tunnel` are intentionally left out — the dev VM uses a real
SMTP relay (below) and its own persistent Cloudflare tunnel process, started
once outside of Compose so app redeploys never touch it.

### One-time VM setup (do once, in the OCI Console)

1. Create an Ampere A1 Compute instance (Always Free-eligible; 2 OCPU/12GB is
   plenty), Ubuntu, in a public subnet. Reserve a static public IP.
2. SSH in, install Docker + the Compose plugin, `git clone` this repo, `cp
   .env.example .env` and fill in real secrets.
3. Start a **quick** Cloudflare tunnel pointed at the API (`cloudflared
   tunnel --url http://localhost:8000`), same as the local `dev` profile's
   `tunnel` service, but run directly on the VM as its own long-lived
   process (systemd unit or `docker run -d --restart unless-stopped
   cloudflare/cloudflared:latest tunnel --url http://host.docker.internal:8000`
   with `--network host` on Linux). Paste the printed URL into Meta's
   WhatsApp webhook config as `https://YOUR-URL.trycloudflare.com/whatsapp/webhook`.
   The URL only changes if this process restarts (e.g. a VM reboot) — repaste
   it then; app redeploys never touch it.
4. In the GitHub repo, add secrets `OCI_DEV_HOST` (the reserved IP),
   `OCI_DEV_SSH_USER`, `OCI_DEV_SSH_KEY` (private key matching a public key
   added to the VM).

### Real SMTP via OCI Email Delivery

For a live prototype demo, `DISPATCHER=smtp` should land mail in a real
inbox rather than a local-only Mailpit UI nobody outside the VM can see. OCI
Email Delivery is Always Free (3,000 emails/month):

1. OCI Console → Email Delivery → approve a sender email/domain (`smtp_from`
   below must be exactly this approved sender — anything else is rejected).
2. Identity & Security → a user → SMTP Credentials → generate one. The
   generated username is an OCID-shaped string, not your account email.
3. In the VM's `.env` only (never commit these):

   ```text
   DISPATCHER=smtp
   SMTP_HOST=smtp.email.<region>.oci.oraclecloud.com
   SMTP_PORT=587
   SMTP_FROM=<your-approved-sender>
   SMTP_USERNAME=<generated-smtp-username>
   SMTP_PASSWORD=<generated-smtp-password>
   ```

   Leaving `SMTP_USERNAME`/`SMTP_PASSWORD` blank keeps the existing
   unauthenticated Mailpit behavior unchanged — this only activates STARTTLS
   + login when both are set.

## Frontend Production Deployment

The frontend is built as static files and served by Nginx. The production image
also proxies same-origin `/api` and `/auth` requests to the Compose `api` service,
serves React Router deep links through `index.html`, disables caching for the SPA
shell, and gives Vite's content-hashed assets a one-year immutable cache policy.

Build and run the complete Docker stack without changing the existing backend
service definitions:

```sh
docker compose --profile prod up -d --build postgres api worker frontend
```

The portal is then available at `http://localhost:8080`. Build-time frontend
settings can be placed in the shell or `.env` before building:

```text
VITE_API_BASE=                 # empty uses the Nginx same-origin proxy
VITE_ASSET_BASE=/              # use /portal/ when deployed below that path
VITE_TILE_URL=https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png
```

These `VITE_*` values are compiled into the JavaScript bundle; changing them
requires rebuilding the frontend image. A custom tile provider must use a Leaflet
URL template and its usage, attribution, and access-token requirements must be
honored. Do not put secrets in any `VITE_*` variable.

### Nginx and Cloudflare

For a direct Nginx deployment, build `frontend/` with `npm ci && npm run build`,
copy `frontend/dist/` to the web root, and adapt
`frontend/nginx/default.conf`. Keep the SPA fallback, immutable caching only for
hashed `/assets/`, no-cache behavior for `index.html`, and the `/api` and `/auth`
proxy routes. If using `VITE_ASSET_BASE=/portal/`, mount the files and SPA fallback
at `/portal/` as well; the provided container configuration targets the domain
root.

Cloudflare may proxy the Nginx service or a load balancer in front of it. Configure
DNS/TLS there, use Full (strict) TLS to a valid origin certificate, and do not
cache `/api/*`, `/auth/*`, or HTML. Cloudflare may cache `/assets/*` while respecting
the origin's immutable cache header. Purge HTML after releases if an additional
Cloudflare cache rule caches it. Restrict the origin to Cloudflare addresses or a
Cloudflare Tunnel where appropriate; never expose database or worker ports.

Verify an origin or proxied deployment before switching traffic:

```sh
curl -I https://example.gov.in/
curl -I https://example.gov.in/assets/ASSET-FROM-DIST.js
curl https://example.gov.in/dashboard
```

The HTML and deep-link responses should be successful with `Cache-Control:
no-cache`; hashed assets should return `Cache-Control: public,
max-age=31536000, immutable`. No image is published and no external deployment is
performed by this repository's CI.
