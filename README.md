# Jan Setu WhatsApp API

FastAPI backend for testing WhatsApp Business send/receive flows for Jan Setu.

## Architecture

- `api` on port `8000`: app-facing APIs and WhatsApp webhook endpoints in one FastAPI service.
- `postgres`: stores contacts, webhook events, incoming messages, and outgoing messages.
- `tunnel`: optional Cloudflare temporary tunnel for local webhook development.

Keeping the webhook inside the same API service is the simplest efficient choice right now. We can split it later only if traffic, deployment, or security boundaries require it.

## Local Setup

Bootstrap local development, including dependencies and the Git pre-commit hook:

```sh
sh scripts/setup-dev.sh
```

Manual equivalent:

```sh
uv sync
uv run pre-commit install
uv run pre-commit run --all-files
```

Start the local database and API:

```sh
cp .env.example .env
docker compose up -d postgres
uv run alembic upgrade head
uv run jan-setu-api
```

For the Dockerized API and database:

```sh
docker compose --profile services up -d --build postgres api
docker compose exec -T api uv run alembic upgrade head
```

Local commands use the host `.venv` created by `uv sync`. Docker commands use the Linux `.venv` baked into the API image by `uv sync --frozen --no-dev`; the Compose API service does not mount the host project over `/app`.

API docs:

```text
http://localhost:8000/docs
```

## Temporary Development Tunnel

With the API running on port `8000`, start a temporary Cloudflare tunnel:

```sh
sh scripts/dev-tunnel.sh
```

The script defaults to Cloudflare's HTTP/2 tunnel protocol, which is usually more stable than QUIC on networks that interfere with UDP traffic.

Use the printed callback URL in Meta:

```text
https://YOUR-TEMP-URL.trycloudflare.com/whatsapp/webhook
```

Use the same verify token as `WHATSAPP_VERIFY_TOKEN` in `.env`.

## WhatsApp Environment Variables

- `WHATSAPP_VERIFY_TOKEN`: token used by Meta to verify the webhook.
- `WHATSAPP_APP_SECRET`: Meta app secret for validating incoming webhook signatures.
- `WHATSAPP_ACCESS_TOKEN`: WhatsApp Cloud API token for sending messages.
- `WHATSAPP_PHONE_NUMBER_ID`: registered WhatsApp Business phone number ID.
- `WHATSAPP_GRAPH_API_VERSION`: Graph API version, default `v20.0`.

Do not commit `.env` or paste permanent tokens into chat.

## API Examples

Verify webhook locally:

```sh
curl "http://localhost:8000/whatsapp/webhook?hub.mode=subscribe&hub.verify_token=dev_verify_token&hub.challenge=hello"
```

List stored contacts:

```sh
curl http://localhost:8000/v1/contacts
```

List stored messages:

```sh
curl http://localhost:8000/v1/messages
```

Send a WhatsApp text message:

```sh
curl -X POST http://localhost:8000/v1/messages/text \
  -H "Content-Type: application/json" \
  -d '{"to":"917652064884","body":"Hello from Jan Setu"}'
```

## Development Checks

```sh
uv run pytest
uv run ruff check .
uv run pre-commit run --all-files
```

Install the Git pre-commit hook once per clone if you did not run the setup script:

```sh
uv run pre-commit install
```

After that, `git commit` automatically runs the configured pre-commit checks. The current hook runs Ruff through `uv`, so it uses this project environment.

## GitHub Merge Checks

GitHub Actions runs pre-commit and pytest on pull requests to `main` through `.github/workflows/ci.yml`.

To block merges until checks pass, enable branch protection in GitHub:

```text
Settings -> Branches -> Add branch protection rule -> main
```

Then require the `Ruff and tests` status check before merging.
