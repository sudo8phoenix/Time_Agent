# Remote Ollama readiness handoff

The adapter accepts HTTPS Tailscale Serve URLs (with default port 443) and Tailscale IPv4 CGNAT addresses in `100.64.0.0/10`. It rejects public destinations, validates all DNS results, sends optional bearer auth only in the Authorization header, and returns generic transport errors that do not include credentials. Chat requests use the §8 generation settings including output/context caps and `think=false`. The new read-only `ops/remote_ollama_check.py` reports runtime, installed tag, digest and selected model metadata without exposing the endpoint or token.

No remote service was contacted and no local service/model was provisioned. The local Ollama daemon started during the preceding abandoned provisioning task has been stopped; the configured `qwen3.5:4b` download did not complete or start after its approval request was interrupted. There is no live endpoint or benchmark result because the friend’s Tailscale URL and model tag have not yet been supplied.

Superseded integration note: typed `ollama_api_key` settings, `.env.example`, worker pipeline wiring, and the fail-fast readiness command are now integrated. The token remains server-only and redacted from results.

Validation was offline only: adapter tests use injected transports; no secrets, network calls, downloads, or database access were used. The exact result is recorded by the orchestrator after the focused unit suite runs.
