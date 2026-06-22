# Jan Setu

FastAPI backend for Jan Setu WhatsApp Business send/receive flows.

## What Runs Locally

- `api`: FastAPI app on `http://localhost:8000`
- `postgres`: local PostgreSQL database on port `5432`
- `tunnel`: optional Cloudflare tunnel for WhatsApp webhook testing

## First-Time Setup

### 1. Install prerequisites

Install these once on your machine:

- Python 3.11+
- Docker Desktop
- `uv`: <https://docs.astral.sh/uv/getting-started/installation/>

On Windows PowerShell, `uv` can be installed with:

```pwsh
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### 2. Clone the repo

```sh
git clone git@github.com:tushar-mahalya/Jan-Setu.git
cd Jan-Setu
```

### 3. Create your local environment file

```sh
cp .env.example .env
```

For normal local development, the example values are enough. Add real WhatsApp values only when testing with Meta.

### 4. Install Python dependencies

```sh
uv sync
uv run pre-commit install
```

Optional one-command setup if your shell can run `.sh` files:

```sh
sh scripts/setup-dev.sh
```

### 5. Start the database

```sh
docker compose up -d postgres
```

### 6. Run migrations

```sh
uv run alembic upgrade head
```

### 7. Start the API

```sh
uv run jan-setu-api
```

Open the API docs:

```text
http://localhost:8000/docs
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

## Run Everything In Docker

Use this if you want the API and database both running in Docker:

```sh
docker compose --profile services up -d --build postgres api
docker compose exec -T api uv run alembic upgrade head
```

The API will still be available at:

```text
http://localhost:8000/docs
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

With the API running on port `8000`, start a temporary Cloudflare tunnel:

```sh
sh scripts/dev-tunnel.sh
```

Use the printed URL in Meta with this path:

```text
https://YOUR-TEMP-URL.trycloudflare.com/whatsapp/webhook
```

Use the same verify token in Meta that you set as `WHATSAPP_VERIFY_TOKEN`.

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

GitHub Actions runs Ruff and tests on pull requests to `main`.
