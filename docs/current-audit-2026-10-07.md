# Current implementation audit — 7 October 2026

## What works now

- The report intake parser accepts pasted text, TXT, DOCX, text PDFs and structured XLSX. It preserves source fragments and locators. Image-only PDFs need transcription; OCR is not implemented.
- Native schedule parsing reads P6 XER/PMXML and Microsoft MSPDI/MPP through the pinned local MPXJ bridge. The checked fixture manifest passed, including a real MPP file and the workspace XER.
- The worker is connected to both processing paths. `AGENT_EXECUTION_MODE=legacy` is the current setting; `graph` selects the bounded LangGraph runtime with PostgreSQL checkpoints. Both paths extract observations, retrieve schedule candidates, validate a selected match, and persist review proposals. Only reviewer approval changes the progress ledger.
- The isolated PostgreSQL integration suite passed 57 tests, including graph checkpoint resume, native imports, report processing, and approval. The backend unit suite passed 154 tests, and six native parser tests passed. Browser fixtures passed four tests, including 390 px and 1440 px review flows. The frontend build and strict TypeScript check passed.

## Fixed during this audit

- Native tasks with an unknown work type remain eligible for model selection when other evidence supports them. A known conflicting work type still excludes a candidate.
- The import screen exposes all leaf activities through search instead of silently stopping after twelve. Reviewers can enter a work type; changing the import or source project clears stale overrides.
- The import baseline date starts empty and must be entered deliberately. The mobile navigation wraps instead of clipping.
- The expanded synthetic dataset manifest now says human review is incomplete, consistent with its AI-assisted review note and limitations. The integrity test reflects the actual review status.
- React declaration packages and Vite environment types are installed, and `npm run typecheck` is available. Production dependencies have no npm audit findings; the development dependency audit still reports five findings and needs a separate upgrade review.

## Next work, in order

1. **Complete task mapping for real schedules.** Imported task names and IDs are available to retrieval, but unmapped quantity baselines remain `unsupported`. Add reviewer controls for area/tags, measurement basis, planned quantity, unit, and aliases when real project data needs numeric progress. Verify a representative source file and report pair through the API and review UI.
2. **Finish graph rollout gates before changing the default.** Implement W-37/W-38 status and trace visibility, then W-39 legacy/graph parity, restart, rollback, security and backup checks. The current graph runtime is wired and tested, but defaulting to it now would bypass those acceptance gates.
3. **Validate the intended model once connected.** Set `OLLAMA_MODEL` to the exact installed Gemma 4 12B tag and configure the private endpoint server-side. Check `/api/version`, `/api/tags`, `/api/show`, structured JSON output, extraction and selection, model digest, latency and representative report accuracy. No Gemma quality or compatibility claim is established by the injected-model tests.
4. **Repair evaluation confidence.** The saved Qwen held-out run used no candidate IDs and no `atomic_event_keys`, so its zero tag/selection/F1 scores do not measure the assembled pipeline. Re-run end-to-end evaluation on reviewed labels after the model and mapping are ready. AI-assisted dataset review does not replace independent human adjudication.
5. **Run a real browser walkthrough.** The current browser tests use fixture or intercepted API responses. Use a real account, database and worker to test import, report intake, pending review, revision, approval, and progress export together.

## Known limits

- At the time of the 7 October audit, live model inference was deferred and the configured model tag was `qwen3.5:4b`. See the 8 October update below. The configured worker mode remains `legacy`.
- Strict validation checks that a model's evidence quote appears in the source. It cannot prove that the model classified the work semantics correctly; human review remains required.
- A report that says only “completed” cannot establish quantity, unit, delta/cumulative meaning or a quantity baseline. The system must surface those missing facts rather than infer a physical percentage.

## 8 October update: Gemma connection and mapping controls

- The local server configuration now targets the private Ollama address and exact `gemma4:12b` tag. The public adapter health check passed with Ollama `0.40.0`, model digest `6114515d63c17436a7c0417d82820ac65ad643e2806c5a3c89cb62846436ed0b0d`, family `gemma4`, size `11.9B`, and quantization `Q4_K_M`. The structured JSON smoke passed and saved the digest in `evaluation/results/gemma4-12b-smoke.json` (4.6 seconds for the chat call in its final run).
- One representative live extraction produced separate observations for completed spool erection and planned welding. It retained `3 spool` only for completed work and preserved source quotes. This call took roughly 100 seconds, so throughput and timeouts still need representative measurement.
- A live single-candidate selection initially returned `unmatched` despite matching area, work type, and asset tag. Selection prompt v3 made the decision rule explicit; the same case then returned `suggested` with the supplied candidate ID and evidence fragment. This is one smoke case, not an accuracy benchmark.
- The native import screen now lets reviewers enter discipline, work type, area, asset tags, aliases, measurement basis, planned quantity, unit, and baseline quantity for each leaf task. Editing a validated mapping requires validation again before staging. Typecheck, build, 154 unit tests, and two fixture browser flows passed; the 390 px import screenshot showed no horizontal overflow.
- PostgreSQL integration could not run during the initial check because the Docker daemon was stopped; it passed later on 8 October (see below). Evaluation on independently reviewed labels and graph rollout gates remain open.

## 8 October footing F-01 live diagnosis

- The user's report `excavated footing in f-01` completed with one observation but no candidate. Gemma placed `f-01` in `area`; retrieval correctly rejected the schedule's `AREA-A` footing because its area differed. The source phrase identifies footing `F-01`, which is an asset tag in the active demo schedule.
- Extraction now normalises an evidenced `footing F01`/`footing F-01` identifier into asset tags. If the model put that same identifier in `area`, the correction clears it and adds a review warning. Candidate payloads now retain schedule asset tags for model selection and review. The extraction prompt is `extraction-v3`.
- A new report was submitted through the live browser after restarting the worker: `On 2026-10-08, excavated footing in f-01.` It produced one `suggested` proposal for `CIV-A-EXC-01` / `Excavate footing F-01`; the review page showed the exact evidence and candidate. The model extracted `area=null` and `asset_tags=[F-01]` directly in this run. The report contains no measured quantity or delta/cumulative meaning, so approval remains disabled without reviewer-supported corrections.
- Verification after the fix: 155 unit tests and 57 isolated PostgreSQL integration tests passed. The earlier report remains an immutable historical job under duplicate-byte intake; explicit audited reanalysis is still pending.

## 8 October `f=01` follow-up

- The exact report `excavated footing on f=01` produced a pending unmatched proposal. Gemma extracted `f=01` as an asset tag, but exact tag comparison excluded the schedule's `F-01` activity. It also incorrectly extracted quantity `1 m` with cumulative meaning from the identifier digits. This false amount was not approved.
- Footing-ID normalization now accepts `f=01`, canonicalizes it to `F-01`, flags the separator for review, and clears any model quantity when the only number in the quoted work statement is the footing ID (excluding an ISO date). Extraction prompt `extraction-v4` explicitly prohibits counting identifier digits as measured work.
- A fresh authenticated API submission of `excavated footing on f=01.` ran through the live worker and Gemma. The agent selected `CIV-A-EXC-01` from one retrieved candidate and saved `quantity=null`, `unit=null`, `quantity_kind=none`, with the separator warning. No numeric progress was applied. After this change, 156 unit tests and 57 isolated PostgreSQL integration tests passed.
