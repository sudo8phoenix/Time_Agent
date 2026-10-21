# Leakage review status

## Current exposure and selection status — 21 October 2026

No assembled production candidate or fresh validation/holdout has been selected
and frozen. Previously evaluated V19 and other captured families remain consumed,
including failed attempts. The ten paired development cases and repeated/source-unit
variants remain development; repeated rows are not independent source families.
Public schedules already supplied do not themselves provide new paired report gold.

Exposure inventories and transitive lineage checks improve eligibility screening;
absence from a capture inventory does not prove freshness. Freeze group-disjoint
inputs/labels, documented AI-assisted review and configuration before new acceptance
capture. Labels stay outside model requests. See the
current checklist (historical local archive),
[freshness gate](../fresh_dataset_preflight.py) and
latest review (historical local archive).

The following inventories retain their dated scope.

## Historical inventory — 18 October 2026

Both `data/evaluation/prototype-v1/` and the later
`data/evaluation/prototype-v19-v2/` have evaluated validation/holdout results.
The V19 validation failed accuracy/readiness, and its eight holdout reports failed
under provider limits. Failed submission and scoring still consume a holdout;
absence of successful predictions does not make it unseen again. Earlier V19-v1
preparation is superseded. See the saved outcomes (historical local archive).

V20 needs fresh validation against every approved target and then a newly frozen
holdout with disjoint groups, declared review policy and pre-capture input/label
hashes. Do not tune on consumed holdout results or relabel development replays as
fresh evaluation. Capture inputs without labels, seal outputs/calls, then score
all frozen cases including failures. No new V20 holdout has been frozen/evaluated
in the 18 October work. See current status (historical local archive).

## Earlier prototype inventory — 17 October 2026

No owner sample is expected. The new inventory is
`data/evaluation/prototype-v1/manifest-v2.json`: eight validation reports and eight
holdout reports across eight separately authored fictional projects. Inputs and
AI-adjudicated labels were hashed before capture; GT10 and prior scope/utility
cases remain development. The capture opens inputs and the manifest only; a
separate scorer opens labels after sealing predictions and calls.
These small AI-authored narrative cases are not independent human gold or owner
evidence. Cambridge remains excluded with its attribution/grouping uncertainties
unresolved. GT10 exclusions are recorded in
`data/review/derived-v1/schedule-dispositions.json`; no source values were corrected.
The older provisional Cambridge discussion below remains historical context.

The provisional Cambridge manifest is group-disjoint by its automatic grouping rules; `data/synthetic/v2/check_splits.py` rechecks this and hashes the exact manifest and proposed labels. GT10 export, input, floors, and all authored report variants are one development family. This is a structural check only. Physical-project/snapshot identity, cross-project dependencies, and near-duplicate grouping need domain review before any freeze.

The proposed Cambridge 221/39/39 project assignment is unbalanced by activity rows (114,583/176,962/152,611) and project type. Development contains 175 Clean Water Networks projects. Those Cambridge validation/heldout partitions remain provisional; the separately frozen synthetic prototype sets above are distinct and now consumed. Cambridge has no independently reviewed report labels. Any manifest or label change requires rerunning its checks and comparisons.

## Existing synthetic benchmark versus release splits

The expanded W-03 dataset has a separately recorded 180/60/60 development/validation/held-out assignment. The 12 October Gemma benchmark (historical local archive) used its existing 60-case held-out assignment, with 12 table-case source locators corrected from report structure. Expected labels were kept out of inference. This older set was previously used with Qwen; it is neither an independently reviewed frozen V2 release split nor proof of unseen project generalization. Cambridge/GT10 V2 partitions and their review/freeze gates remain as described above.
