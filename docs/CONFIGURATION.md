# Configuration reference

Settings are loaded from environment variables and local `.env` at process startup.
Restart API and workers deliberately after changes. Existing durable runs retain
pinned identities and may reject incompatible changes. Never commit private `.env`.

Start with [the environment template](../.env.example) and
[the selected local profile](local-run.md). Defaults below come from `Settings`,
not the current private workspace configuration. Blank role overrides inherit the
base provider/model according to runtime resolution.

| Variable | Default | Purpose |
|---|---|---|
| `APP_NAME` | `site-progress-agent` | Server-side runtime setting; see related guide below |
| `ENVIRONMENT` | `development` | development, test or production; production enables Secure cookies |
| `DATABASE_URL` | `postgresql+psycopg://progress:progress@127.0.0.1:5432/progress` | Application PostgreSQL connection; use isolated URLs for tests |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Server-side runtime setting; see related guide below |
| `OLLAMA_MODEL` | `qwen3.5:4b` | Server-side runtime setting; see related guide below |
| `LLM_PROVIDER` | `ollama` | Base provider: ollama, groq, openrouter or gonka |
| `GROQ_API_KEY` | `unset` | Server-side runtime setting; see related guide below |
| `GROQ_API_KEY_1` | `unset` | Server-side runtime setting; see related guide below |
| `GROQ_API_KEY_2` | `unset` | Server-side runtime setting; see related guide below |
| `GROQ_ACCOUNT_SCOPES_ENABLED` | `False` | Opt-in reviewed account-scope admission policy |
| `GROQ_MODEL` | `openai/gpt-oss-20b` | Server-side runtime setting; see related guide below |
| `OPENROUTER_API_KEY` | `unset` | Server-side runtime setting; see related guide below |
| `OPENROUTER_MODEL` | `unset` | Explicit OpenRouter model ID |
| `GONKA_BROKER_LLM` | `unset` | Private Gonka Broker key; shared across Gonka roles |
| `GONKA_MODEL` | `unset` | Explicit Gonka model ID; no implicit model default |
| `ORCHESTRATOR_PROVIDER` | `unset` | Server-side runtime setting; see related guide below |
| `ORCHESTRATOR_MODEL` | `unset` | Server-side runtime setting; see related guide below |
| `ORCHESTRATOR_KEY_SLOT` | `0` | Server-side runtime setting; see related guide below |
| `EXTRACTION_PROVIDER` | `unset` | Server-side runtime setting; see related guide below |
| `EXTRACTION_MODEL` | `unset` | Server-side runtime setting; see related guide below |
| `EXTRACTION_KEY_SLOT` | `0` | Server-side runtime setting; see related guide below |
| `SELECTION_PROVIDER` | `unset` | Server-side runtime setting; see related guide below |
| `SELECTION_MODEL` | `unset` | Server-side runtime setting; see related guide below |
| `SELECTION_KEY_SLOT` | `0` | Server-side runtime setting; see related guide below |
| `REPORT_MODEL_TIMEOUT_SECONDS` | `360` | Server-side runtime setting; see related guide below |
| `CONVERSATION_MODEL_TIMEOUT_SECONDS` | `300` | Server-side runtime setting; see related guide below |
| `OLLAMA_API_KEY` | `unset` | Server-side runtime setting; see related guide below |
| `SECRET_KEY` | `development-only-change-me` | Production requires a random private secret of at least 32 characters; shared login counters require the same secret across workers |
| `REGISTRATION_ENABLED` | unset | Defaults to false in production and true otherwise; true permits reviewer self-registration |
| `FRONTEND_DIST` | `frontend/dist` | Built frontend directory |
| `UPLOAD_DIR` | `uploads` | Persistent original-file root |
| `PARSER_SOCKET_PATH` | `/run/site-parser/parser.sock` | Bounded Unix-socket transport to the isolated Docker parser service; no local fallback |
| `AGENT_EXECUTION_MODE` | `graph` | Server-side runtime setting; see related guide below |
| `AGENT_HIERARCHY_ENABLED` | `False` | Select V2 and durable new conversations |
| `ORCHESTRATOR_MODEL_ASSISTED` | `False` | Enable legal-action model planner |

Gonka targets `https://proxy.gonkabroker.com/v1/chat/completions`. Its planner
allowlist is `MiniMaxAI/MiniMax-M2.7` and `deepseek-ai/DeepSeek-V4-Flash-0731`.
Groq planners support `openai/gpt-oss-20b`, `openai/gpt-oss-120b` and
`qwen/qwen3.8-27b`. An allowed configuration is not evidence of successful model
behavior; see the [role comparison](FOUR_MODEL_ROLE_COMPARISON.md).

## Operational relationships

`GROQ_API_KEY` is slot 0; `_1` and `_2` are slots 1 and 2. Different slots do not
prove independent account quota. Do not enable account scopes without the reviewed
procedure in [provider capacity](provider-capacity.md).

Provider keys stay on the server. OpenRouter and Gonka require an explicit model ID; the
planner has an allowlist distinct from extraction/selection support. Report and
conversation timeouts include admission waits. Ollama model names must match an
installed endpoint model. See [generation settings](model-generation-settings.md)
for request settings and [durable configuration](durable-model-configuration.md)
for upgrade/resumption behavior. Production environment mode does not validate all
hosting, security or capacity prerequisites; follow [deployment](DEPLOYMENT.md).

---

[Documentation index](README.md) · [Project overview](../README.md)
