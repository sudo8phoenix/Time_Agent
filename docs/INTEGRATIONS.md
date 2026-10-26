# Integrations and supported formats

## Input compatibility

| Source | Supported route / format | Boundary |
|---|---|---|
| Generic schedule | Direct CSV schedule import | Must satisfy application schedule schema |
| Primavera P6 | XER and recognized P6 XML | File import; no live P6 API connector |
| Microsoft Project | MPP and MSPDI XML | Java/MPXJ-backed file import; no live Project synchronization |
| GT10 dataset | Reviewed GT10 XLSX | Dataset-specific reader, not arbitrary schedule XLSX |
| Cambridge dataset | Derived JSON snapshots | Expected dataset structure, not arbitrary JSON |
| Reports | Text, DOCX, text PDF, mapped/required-column XLSX | See exact limits in document support |
| Scans and images | PDF transcription workflow; standalone images unsupported | No OCR or vision processor |

Native sources are inspected, source-project selected when necessary, mapped,
staged and explicitly activated. Staging does not activate the schedule. Preserve
baseline and reviewer mapping reasons. Import does not promise faithful round-trip
export of every original scheduling field or vendor feature.

## PMIS delivery

```mermaid
flowchart LR
    A[Approved activity state] --> O[Transactional outbox snapshot]
    O --> C[Connector worker]
    C -->|HTTP + idempotency key| M[MOCK PMIS receiver]
    M --> R[Receipt / read-back]
```

The shipped adapter is labeled **MOCK PMIS — prototype**. Payloads include project
and external activity identity, source schedule/version, state revision, quantity,
percentage and lifecycle endpoints. Pending/retry/failed older revisions block later
revisions of the same activity. Transient delivery failures use bounded exponential
retry delays; permanent failures require diagnosis. Application approval remains
committed even when delivery fails.

Start the receiver/connector using the [local runbook](local-run.md). Restrict the
connector by project when needed. Back up receiver SQLite independently.
A production adapter must define authentication, identity mapping, accepted field
semantics, idempotency, ordering, reconciliation, timeout/error handling and test
coverage against the actual target. None of that is established by a mock receipt.

Source: [adapter contract](../backend/app/integrations/base.py),
[outbox](../backend/app/integrations/outbox.py),
[native format dispatch](../backend/app/ingest/native_schedule/dispatch.py).

## Model providers

Ollama, Groq, OpenRouter and Gonka are server-side model providers. Each role may
pin a different provider/model; credentials remain private. Gonka uses its Broker
OpenAI-compatible endpoint through the bounded JSON adapter, with an explicit
model ID, a 4096-token ceiling and complete-fence normalization followed by local
schema validation. The planner separately requests only 128 tokens.

See [configuration](CONFIGURATION.md), [generation settings](model-generation-settings.md)
and [capacity coverage](provider-capacity.md). DeepSeek selection passed all 30
saved identity decisions in the [four-model comparison](FOUR_MODEL_ROLE_COMPARISON.md),
but its updated-adapter planner passed 0/3 legal transitions. Configuration support
and a successful role rehearsal do not establish end-to-end integration readiness.

---

[Documentation index](README.md) · [Project overview](../README.md)
