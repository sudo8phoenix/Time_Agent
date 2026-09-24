# Local runbook

This profile runs the application and PostgreSQL on this Mac. Ollama may run on a friend's laptop through a private Tailscale connection; public hosting is intentionally deferred.

## One-time setup

Requirements: Python 3.12, Node.js/npm, Docker Desktop, and Java. From `site-progress-agent/`:

```sh
cp .env.example .env
make bootstrap
cd frontend && npm ci && cd ..
make db-up
make migrate
make build-web
```

Edit `.env` before creating real data. Replace `SECRET_KEY` with a long random value. Keep `ENVIRONMENT=development` for plain `http://127.0.0.1`; production cookies require HTTPS.

Create the local reviewer and demo schedule without resetting existing data:

```sh
DEMO_PASSWORD='choose-at-least-12-characters' make seed-demo
```

The username is `demo-reviewer`. Do not commit `.env` or share the password.

## Remote Ollama configuration

After the friend-host endpoint is ready, put its private Tailscale HTTPS URL and exact installed tag in `.env`:

```dotenv
OLLAMA_BASE_URL=https://model-host.example.ts.net
OLLAMA_MODEL=exact-installed-tag
OLLAMA_API_KEY=
```

Then run the non-generating readiness check:

```sh
make remote-check
```

This check has a 10-second timeout, does not send report content, and does not print the endpoint or token. See [remote-ollama.md](remote-ollama.md) for the friend-host setup and network restrictions.

## Start the app

Use two terminals from the project directory:

```sh
make serve
```

```sh
make worker
```

Open `http://127.0.0.1:8000`. The API serves the already-built frontend from `frontend/dist`; rerun `make build-web` after frontend changes.

The worker is deliberately single-process for the laptop profile. Stop it with Ctrl-C; durable jobs may be reclaimed after their lease expires.

Hybrid retrieval uses the optional local `sentence-transformers/all-MiniLM-L6-v2` adapter only when its pinned runtime and weights have already been provisioned on this Mac. It never downloads weights while processing a job. Until those assets are installed, the worker reports the limitation and safely uses lexical retrieval; do not describe that fallback as a measured hybrid-model result.

## Checks

```sh
make doctor
make test-unit
make test-integration
make native-smoke
cd frontend && npm run build && node tests/frontend-contracts.test.mjs
```

`make doctor` is expected to fail the model-endpoint item until the friend's endpoint and exact model tag are configured.

## Backup and restore drill

Stop intake and the worker before the backup:

```sh
make backup ARGS="--output /absolute/new/backup-directory --quiesced"
make restore-verify ARGS="/absolute/backup-directory --database progress_restore_example --uploads /absolute/new/restore-uploads"
```

Restore verification refuses to replace an existing database and leaves the separate restored database available for inspection.

## Still requires a person

- Supply and verify the friend's private Ollama URL and exact model tag.
- Review the W-03 and W-29 proposed labels before they become evaluation truth.
- Perform the browser walkthrough and demo rehearsal on the actual laptops/network.
- Decide on hosting later; no public exposure is part of this runbook.
