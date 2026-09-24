# W-10-FIX handoff

- Task ID: W-10-FIX
- Changed files: `backend/app/retrieval/index.py`, `backend/tests/unit/test_retrieval.py`.
- Behaviour: an exact eligible leaf `explicit_activity_id` is retained even when
  no lexical or embedding rank exists. The fallback candidate has null ranks,
  zero scores, and is ordered before other candidates; remaining slots are
  filled by normally fused eligible candidates. Missing IDs never appear,
  summaries, area conflicts, and asset-tag conflicts remain excluded, and the
  existing maximum candidate bound is preserved.
- Acceptance command: `.venv/bin/pytest backend/tests/unit/test_retrieval.py -q`
- Result: `7 passed`.
- Evidence: the retrieval suite covers exact-ID ordering, an exact ID with no
  component ranks, fused fillers, missing IDs, leaf filtering, metadata
  conflicts, and the eight-candidate limit.
- Limitations: no model, embedding service, network, or production schedule was
  used; the suite uses synthetic in-memory rows.
- Contract changes: none.
- Next task unblocked: W-11 selection and abstention integration.
