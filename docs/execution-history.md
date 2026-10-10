# Execution history and duration API

All reads require an authenticated project member. Paths below are relative to `/api/v1/projects/{project_id}`. `version` selects a schedule version; omitting it uses the active version.

| Path | Behavior |
| --- | --- |
| `/history` | Accepted events, immutable values and explicit current projection; limit 1–200, offset ≥ 0. |
| `/exports/approved.csv` | All accepted events including superseded/retracted records; CSV cells are formula protected. |
| `/exports/approved.json` | Same event coverage with nested evidence, provenance, confidence and decisions. |
| `/blockers` | Recurring causes from active accepted blocker events; correction chains counted once. |
| `/durations` | Current whole-activity elapsed/date-span results; bounded pagination and optional work type filter. |

History filters: `activity_id` (internal UUID), `discipline`, `work_type`, `date_from`, `date_to` (inclusive work dates), `blocker` (category or `any`), `status` (`active`, `superseded`, `retracted`, `retraction`) and `correction_status` (`original`, `correction`, `retraction`). History and exports also support `active_only=true`. Use `next_offset` to continue pagination. Date filters refer to work date, not approval/submission time.

`accepted_values` records the values for that particular immutable event. `latest_activity_state` is the current projection at query time. CSV uses explicit `latest_*` names for current state; migrate consumers of the old ambiguous `actual_start`, `actual_finish`, `physical_percent` and `approved_completed_quantity` columns. A corrected original retains its original endpoint and quantities. Withdrawing a correction withdraws its ancestor chain; originals do not become active again. Retraction tombstones are historical records, not active updates.

Blocker acceptance requires an eligible pinned activity, work date, source evidence and reviewer-confirmed category, without quantity/percent. Reviewers can submit a pending correction at `/api/v1/proposals/events/{event_id}/correct-blocker` using `expected_activity_revision`, `blocker`, `blocker_category`, `effective_date`, `evidence` and `reason`. Acceptance follows the normal proposal endpoint and revision/idempotency contract. The initial category `other` is deliberately conservative. Corrections retain old evidence and decisions; active aggregation counts the latest accepted category once.

Duration queries use accepted lifecycle endpoint references, including precision and timezone. Supported timed endpoints yield elapsed seconds plus minimum/maximum precision bounds. Date-only or mixed precision yields a date span and explicit clock-time uncertainty. Missing endpoint or timezone yields an unavailable reason. Daylight-saving gaps/folds require an explicit consistent instant. Elapsed time does not establish continuous productive work.

Calendar-working duration is distinct. The pure service supports explicitly reviewed/versioned same-day shifts, breaks and holiday dates, carries precision bounds and rejects unsupported/malformed/DST-ambiguous inputs. No source calendar currently meets the review/definition gate: Cambridge shapes and timezones remain unreviewed, and GT10 has only a calendar name. The operational endpoint therefore reports calendar-working time unavailable. It never infers a six-day/eight-hour calendar. No measured compatible crew-hour/allocation data exist, so crew-hour productivity remains unavailable even when quantity or elapsed/calendar time exists.
