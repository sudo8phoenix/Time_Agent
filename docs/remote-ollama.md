# Remote Ollama over Tailscale

The worker can call an Ollama instance on a different network through a Tailscale tailnet. The worker accepts only loopback, private, link-local, or Tailscale CGNAT addresses (`100.64.0.0/10`); public resolved addresses are rejected. HTTPS URLs may omit the port and use 443. TLS certificate verification remains enabled.

On the model host, both laptops need to join the same tailnet. Keep Ollama bound to its local interface, then use Tailscale Serve to proxy the local Ollama port privately:

```sh
tailscale serve 11434
```

Enable HTTPS certificates for the tailnet if prompted. Serve publishes the service only inside that tailnet. Do not use Tailscale Funnel, router port forwarding, or a public reverse proxy without authentication. Apply a least-privilege Tailscale grant for the worker laptop to reach the model host; a newly created tailnet may allow more devices by default. Alternatively use an authenticated reverse proxy with a server-side bearer token. A Tailscale Serve HTTPS URL uses a `https://device.tailnet.ts.net` form and is accepted by the worker. See [Tailscale Serve](https://tailscale.com/docs/features/tailscale-serve) and [tailnet policy grants](https://tailscale.com/docs/reference/syntax/policy-file).

On the worker host, configure the endpoint and exact model tag through the existing runtime settings:

```dotenv
OLLAMA_BASE_URL=https://model-host.example.ts.net
OLLAMA_MODEL=the-installed-tag
OLLAMA_API_KEY=   # optional, only when the proxy requires Bearer authentication
```

`OLLAMA_API_KEY` is read by typed backend settings as a secret and sent as an `Authorization: Bearer` header. Never put it in frontend configuration, URLs, report content, command-line arguments, source control, or logs. Tailscale Serve itself uses tailnet access control and does not require this bearer token.

Before running jobs, use `make remote-check` (or `python ops/remote_ollama_check.py --timeout 10`). It checks the runtime version, exact installed model tag, model digest, family, parameter size and quantization when available. It never prints the URL or token, never sends a prompt, disables retries, and returns nonzero if the runtime is unreachable or the configured model is missing.

The adapter keeps the §8 starting generation settings: `stream=false`, schema-constrained output, `temperature=0`, `num_ctx=8192`, `num_predict=1536`, and `think=false`. Callers may request smaller context/output limits but cannot raise those two caps. Ollama's [chat API](https://docs.ollama.com/api/chat) specifies `think` control and says supported values depend on the selected model. If it does not support the field, construct the adapter with `think=None` to omit it. This readiness check does not benchmark throughput or verify the pinned tokenizer's 6,144-token input budget.
