# Changelog

Changes affecting users and operators are recorded here. Package version `0.1.0`
is a prototype identifier, not evidence of a tagged production release.

## Unreleased

### Model providers and recovery

- Add explicit Gonka role configuration, bounded JSON handling and shared transport admission.
- Add Groq structured-output compatibility, safe failure diagnostics and a bounded
  graph correction for generated-schema rejections; surface actionable UI errors.
- Defer report claims during known Groq/OpenRouter cooldowns and retain failing stages.
- Document the four-model rehearsal, including DeepSeek selection strengths and
  planner failures, current configuration and remaining Gonka telemetry/pre-claim limits.

### Documentation

- Add API/OpenAPI reference, agent architecture, database entity reference, security
  threat model, deployment prerequisites, user workflow and integration boundaries.
- Add matching/data-flow diagrams, observability, configuration, troubleshooting
  and contribution guides; organize maintained documents by audience.
- Publish the existing evaluation research report and proprietary licensing terms.

## 0.1.0 — prototype baseline

The current package declares version 0.1.0; no release date is asserted here.
The existing application includes versioned schedule import, document intake,
bounded report/conversation analysis, evidence-first review, an approved-progress
ledger, exports and mock PMIS outbox delivery. See the maintained testing guide
for verified scope and open production acceptance work.
