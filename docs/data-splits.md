# Leakage review status

The provisional Cambridge manifest is group-disjoint by its automatic grouping rules; `data/synthetic/v2/check_splits.py` rechecks this and hashes the exact manifest and proposed labels. GT10 export, input, floors, and all authored report variants are one development family. This is a structural check only. Physical-project/snapshot identity, cross-project dependencies, and near-duplicate grouping need domain review before any freeze.

The proposed 221/39/39 project assignment is unbalanced by activity rows (114,583/176,962/152,611) and project type. Development contains 175 Clean Water Networks projects. Current validation and heldout partitions are candidates, not frozen benchmark data. No independently reviewed report labels or fresh heldout scenarios exist, so thresholds and unseen outcome claims remain blocked. Any manifest or label change requires rerunning the check and all comparisons.

## Existing synthetic benchmark versus release splits

The expanded W-03 dataset has a separately recorded 180/60/60 development/validation/held-out assignment. The [12 October Gemma benchmark](../evaluation/RESULTS.md) used its existing 60-case held-out assignment, with 12 table-case source locators corrected from report structure. Expected labels were kept out of inference. This older set was previously used with Qwen; it is neither an independently reviewed frozen V2 release split nor proof of unseen project generalization. Cambridge/GT10 V2 partitions and their review/freeze gates remain as described above.
