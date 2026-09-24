"""Local, deterministic activity retrieval (W-10).

The index is deliberately storage agnostic: callers can pass SQLAlchemy rows or
plain mappings, and provide an embedding function backed by a pinned local model.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import hashlib, math, re
from typing import Any, Callable, Iterable, Mapping, Sequence

INDEX_VERSION = "retrieval-v1"
_TOKEN = re.compile(r"[a-z0-9][a-z0-9_-]*")

def _get(x: Any, key: str, default=None):
    return x.get(key, default) if isinstance(x, Mapping) else getattr(x, key, default)

def _norm(value: Any) -> str:
    return " ".join(str(value or "").lower().split())

def _terms(value: Any) -> set[str]:
    return set(_TOKEN.findall(_norm(value)))

def _split(value: Any) -> set[str]:
    return {_norm(v) for v in re.split(r"[,;|]", str(value or "")) if _norm(v)}

def compose_description(activity: Any, max_chars: int = 1200) -> str:
    """Compose bounded embedding text with identity fields first."""
    fields = [_get(activity, "name", ""), _get(activity, "discipline", ""),
              _get(activity, "work_type", ""), _get(activity, "area", ""),
              _get(activity, "asset_tags", ""), _get(activity, "wbs", _get(activity, "wbs_path", "")),
              _get(activity, "aliases", "")]
    text = " | ".join(str(v or "") for v in fields)
    return text[:max_chars]

@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    external_id: str
    activity_name: str
    area: str | None
    work_type: str
    is_leaf: bool
    lexical_rank: int | None = None
    embedding_rank: int | None = None
    lexical_score: float = 0.0
    embedding_score: float | None = None
    rrf_score: float = 0.0
    conflict_flags: tuple[str, ...] = ()

    @property
    def activity_id(self) -> str:
        """Compatibility alias for retrieval/evaluation callers."""
        return self.candidate_id

    @property
    def retrieval_rank(self) -> int | None:
        ranks = [rank for rank in (self.lexical_rank, self.embedding_rank) if rank is not None]
        return min(ranks) if ranks else None

    @property
    def retrieval_score(self) -> float:
        return max(self.lexical_score, self.embedding_score or 0.0)

@dataclass
class RetrievalResult:
    candidates: list[Candidate]
    conflicts: list[str] = field(default_factory=list)
    excluded_activity_ids: list[str] = field(default_factory=list)
    cache_key: str = ""
    index_version: str = INDEX_VERSION
    model_version: str = "none"

def cache_key(schedule_version_id: Any, activities: Iterable[Any], model_version: str = "none", text_version: str = "text-v1") -> str:
    rows = sorted((str(_get(a, "id", _get(a, "activity_id", ""))), str(_get(a, "external_id", "")), compose_description(a)) for a in activities)
    payload = repr((str(schedule_version_id), model_version, text_version, rows)).encode()
    return hashlib.sha256(payload).hexdigest()

def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) != len(b): return 0.0
    dot = sum(x*y for x, y in zip(a,b)); na = math.sqrt(sum(x*x for x in a)); nb = math.sqrt(sum(y*y for y in b))
    return dot / (na * nb) if na and nb else 0.0

def retrieve_candidates(observation: Any, schedule_version_id: Any, activities: Iterable[Any] = (), *, embed: Callable[[str], Sequence[float]] | None = None, activity_embeddings: Mapping[str, Sequence[float]] | None = None, model_version: str = "none", text_version: str = "text-v1", max_candidates: int = 8) -> RetrievalResult:
    """Retrieve at most eight eligible leaf activities using lexical + local embeddings."""
    rows = list(activities)
    key = cache_key(schedule_version_id, rows, model_version, text_version)
    area = _norm(_get(observation, "area")); tags = {_norm(t) for t in (_get(observation, "asset_tags", []) or []) if _norm(t)}
    explicit = _norm(_get(observation, "explicit_activity_id"))
    obs_terms = _terms(" ".join(str(_get(observation, k, "") or "") for k in ("summary", "area", "work_type", "discipline", "asset_tags", "explicit_activity_id")))
    eligible=[]; exact_eligible=[]; conflicts=[]; excluded=[]
    for a in rows:
        aid, ext = str(_get(a,"id",_get(a,"activity_id",_get(a,"external_id","")))), str(_get(a,"external_id",""))
        if not _get(a,"is_leaf",True): excluded.append(aid); continue
        ca, ct = _norm(_get(a,"area")), _split(_get(a,"asset_tags"))
        flags=[]
        if area and ca and area != ca: flags.append("AREA_CONFLICT")
        if tags and ct and not tags.intersection(ct): flags.append("TAG_CONFLICT")
        if flags:
            excluded.append(aid); conflicts.append(f"{aid}:" + ",".join(flags)); continue
        eligible.append((a, aid, ext))
        if explicit and _norm(ext) == explicit:
            exact_eligible.append((a, aid, ext))
    lexical=[]
    for a, aid, ext in eligible:
        text_terms = _terms(" ".join(str(_get(a,k,"") or "") for k in ("name","wbs","wbs_path","aliases","area","asset_tags","work_type","discipline")))
        lexical.append((len(obs_terms & text_terms) / max(1, len(obs_terms | text_terms)), aid, a, ext))
    lexical.sort(key=lambda x: (-x[0], x[1])); lexrank={x[1]:(i+1,x[0]) for i,x in enumerate(lexical[:20])}
    emb_rank={}; vectors={}
    if embed:
        q=embed(_norm(_get(observation,"summary"))); scored=[]
        for a, aid, ext in eligible:
            try:
                vector = activity_embeddings.get(aid) if activity_embeddings is not None else embed(compose_description(a))
                score = _cosine(q, vector) if vector is not None else 0.0
            except (TypeError, ValueError): score=0.0
            scored.append((score,aid)); vectors[aid]=score
        scored.sort(key=lambda x:(-x[0],x[1])); emb_rank={aid:(i+1,s) for i,(s,aid) in enumerate(scored[:20])}
    fused=[]
    for a, aid, ext in eligible:
        lr, ls = lexrank.get(aid,(None,0.0)); er, es = emb_rank.get(aid,(None,None)); rrf=(1/(60+lr) if lr else 0)+(1/(60+er) if er else 0)
        if lr or er:
            fused.append(Candidate(
                candidate_id=aid,
                external_id=ext,
                activity_name=str(_get(a, "name", "")),
                area=_get(a, "area"),
                work_type=str(_get(a, "work_type", "unknown")),
                is_leaf=bool(_get(a, "is_leaf", True)),
                lexical_rank=lr,
                embedding_rank=er,
                lexical_score=ls,
                embedding_score=es,
                rrf_score=rrf,
            ))
    fused.sort(key=lambda c:(-c.rrf_score,c.activity_id))
    if explicit:
        exact=[c for c in fused if _norm(c.external_id)==explicit]
        # An exact eligible ID is authoritative even when neither retrieval
        # channel produced a rank. Preserve that absence in the candidate's
        # rank/score fields instead of inventing evidence.
        if not exact and exact_eligible:
            a, aid, ext = exact_eligible[0]
            exact = [Candidate(
                candidate_id=aid,
                external_id=ext,
                activity_name=str(_get(a, "name", "")),
                area=_get(a, "area"),
                work_type=str(_get(a, "work_type", "unknown")),
                is_leaf=bool(_get(a, "is_leaf", True)),
            )]
        fused=exact + [c for c in fused if c not in exact]
    return RetrievalResult(fused[:max_candidates], conflicts, excluded, key, INDEX_VERSION, model_version)

def recall_at_8(results: Iterable[RetrievalResult], expected_external_ids: Iterable[str]) -> float:
    expected=list(expected_external_ids); found=sum(1 for r,e in zip(results,expected) if any(_norm(c.external_id)==_norm(e) for c in r.candidates[:8])); return found / len(expected) if expected else 0.0

__all__=["Candidate","RetrievalResult","compose_description","cache_key","retrieve_candidates","recall_at_8"]
