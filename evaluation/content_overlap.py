"""Conservative lexical overlap screening; candidates need lineage review.

Fingerprints retain digits/IDs and contain no source text. A similarity flag is
not proof of ancestry, and absent lexical overlap is not proof of independence.
"""

from hashlib import sha256
import re


def fingerprint(text):
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Nonempty source text required")
    if len(text) > 200_000:
        raise ValueError("Source exceeds bounded overlap-screening limit")
    tokens = re.findall(r"\w+(?:[-.]\w+)*", text.casefold())
    if not tokens:
        raise ValueError("Source contains no lexical tokens")
    width = min(3, len(tokens))
    shingles = sorted({sha256(" ".join(tokens[i:i + width]).encode()).hexdigest()
                       for i in range(len(tokens) - width + 1)})
    return dict(normalized_sha256=sha256(" ".join(tokens).encode()).hexdigest(),
                shingles=shingles)


def compare(left, right):
    if left["normalized_sha256"] == right["normalized_sha256"]:
        return 1.0
    a, b = set(left["shingles"]), set(right["shingles"])
    return len(a & b) / len(a | b) if a or b else 0.0


def cross_split_candidates(rows, known=(), *, threshold=0.75):
    if type(threshold) not in (int, float) or not 0 < threshold <= 1:
        raise ValueError("Explicit similarity threshold in (0, 1] required")
    if len(rows) + len(known) > 2000:
        raise ValueError("Too many sources for bounded pairwise overlap screening")
    candidates = []
    comparisons = 0
    for index, row in enumerate(rows):
        previous = list(rows[:index]) + list(known)
        for other in previous:
            if row["split"] == "development" and other["split"] == "consumed":
                continue
            if row["split"] == other["split"]:
                continue
            if "fingerprint" not in row or "fingerprint" not in other:
                continue
            comparisons += 1
            similarity = compare(row["fingerprint"], other["fingerprint"])
            if similarity >= threshold:
                candidates.append(dict(case_id=row["case_id"], other_case_id=other["case_id"],
                                       split=row["split"], other_split=other["split"],
                                       similarity=similarity, lineage_confirmed=False))
    return dict(candidates=candidates, comparisons=comparisons, threshold=threshold,
                independence_certified=False)
