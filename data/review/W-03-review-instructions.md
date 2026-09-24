# W-03 expanded synthetic-label review

Status: **pending human review**. This package contains generated synthetic inputs and proposed labels, not verified gold data.

1. Open `w03-expanded-review.csv` beside `../synthetic/expanded/reports.jsonl` and `labels.jsonl`. For each row, verify the cited fragment, eligible activity IDs, mapping state, event type, quantity/kind/unit, dates, and whether an expected effect is safe. Record `approved`, `corrected`, or `rejected` in `review_decision`, your identifier, and a concise note.
2. A second reviewer independently reviews every `ambiguous_match` and `duplicate_correction_quantity` row plus a random 10% sample (at least 30) of other rows. Record the second decision.
3. Resolve disagreements in `adjudication`; do not silently overwrite the original proposed values. Update reviewer status only after the recorded decision.
4. Do not reveal `held_out` labels to the person/model producing predictions. Keep the split file with this package.
5. Corrected labels need a fresh hash/manifest update and a review log. Do not report accuracy or human-review completion until this is done.
