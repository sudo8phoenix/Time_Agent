# Contributing

Time Agent is a local prototype. Read the [proprietary license](../LICENSE) before
using or redistributing the code. A contribution does not change those terms.

## Development workflow

1. Read [setup](local-run.md), [architecture](SYSTEM.md) and [security](SECURITY.md).
2. Create a branch for a focused change. Use synthetic/public fixtures and keep
   private data, `.env`, uploads, raw captures and credentials out of commits.
3. Follow the existing Python/TypeScript patterns and Ruff configuration in
   `pyproject.toml`. Preserve evidence, scope checks, revisions and durable budgets.
4. Add meaningful regression coverage for behavior changes. Database changes need
   a new Alembic migration and isolated integration verification.
5. Update the relevant guide, API snapshot and changelog when behavior changes.
6. Open a PR describing the concrete problem, final behavior, validation and
   material limitations. Do not claim live model quality from deterministic tests.

## Checks

```sh
make test-unit
make test-integration
.venv/bin/python -m ruff check backend evaluation ops
cd frontend
npm run typecheck
npm run build
npm run test:e2e
```

Run scoped lint for a focused change and report existing unrelated failures clearly.
Integration tests require isolated `progress_test`/rehearsal databases. Live model
studies consume quota and require separate frozen inputs and budgets. Current CI
runs unit tests, frontend typecheck and build; local integration/browser results
must be reported separately. See [testing](TESTING_AND_QUALITY.md).

## Documentation changes

Use relative links, concise tables and GitHub Mermaid diagrams. Label fixture
screenshots and measured versus planned behavior. Avoid links to ignored local
archives in maintained guides. Regenerate schema/config/entity references after
changing their code sources. Keep original historical evidence unchanged.

Bugs: use GitHub Issues with reproduction steps and sanitized diagnostics.
Vulnerabilities: follow [security reporting](SECURITY.md).

---

[Documentation index](README.md) · [Project overview](../README.md)
