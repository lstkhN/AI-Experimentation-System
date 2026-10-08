"""Turn provider research results into persisted, traceable evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from typing import Iterable

from sqlalchemy.exc import IntegrityError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Evidence, EvidenceLink, EvidenceSource, Hypothesis, Project
from app.services.research import MAX_CONTENT_LENGTH, ResearchResult, json_normalize

_TRACKING_PARAMETERS = {"gclid", "fbclid", "mc_cid", "mc_eid"}
MAX_TITLE_LENGTH = 500


@dataclass(frozen=True)
class NormalizationSummary:
    sources_created: int = 0
    evidence_created: int = 0
    evidence_reused: int = 0
    results_skipped: int = 0


def canonical_url(url: str) -> str | None:
    """Return a stable web URL, dropping fragments and common tracking params."""
    parsed = urlsplit(url.strip())
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return None
    host = parsed.netloc.lower()
    path = parsed.path.rstrip("/") or "/"
    query = urlencode(sorted((key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True)
                            if not key.lower().startswith("utm_") and key.lower() not in _TRACKING_PARAMETERS))
    return urlunsplit((parsed.scheme.lower(), host, path, query, ""))


def source_cluster(url: str) -> str:
    """A publisher/domain is one source cluster for independence purposes."""
    return urlsplit(url).hostname.lower().removeprefix("www.")  # type: ignore[union-attr]


def canonical_source_cluster(url: str | None) -> str:
    """Derive the sole URL-based source cluster used by research workflows."""
    normalized_url = canonical_url(url) if url else None
    return source_cluster(normalized_url) if normalized_url else "unknown"


def _snippet(result: ResearchResult) -> tuple[str, bool, int]:
    """Bound snippet retention even for results supplied outside our adapter."""
    content = result.content if isinstance(result.content, str) else ""
    original_length = result.original_content_length if result.original_content_length is not None else len(content)
    truncated = result.content_truncated or len(content) > MAX_CONTENT_LENGTH
    return content[:MAX_CONTENT_LENGTH], truncated, original_length


def _classification() -> dict[str, str]:
    """Classify unreviewed search snippets conservatively and reproducibly.

    A search result does not carry an asserted relation to a hypothesis.  It is
    therefore provenance, not supporting evidence, until a user or a dedicated
    claim-extraction/review flow supplies that relation.
    """
    return {"direction": "neutral", "tier": "E0", "relation": "unknown", "reason": "unreviewed_search_snippet"}


def _provenance_timestamp(value: datetime | str | None) -> str | None:
    """Return a JSON-safe, UTC timestamp for persisted provider provenance."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    return value


def _source_identity(normalized_url: str) -> str:
    """Derive the persistent source key from the canonical, not raw, URL."""
    return sha256(f"url:{normalized_url}".encode("utf-8")).hexdigest()


def _provenance(result: ResearchResult, normalized_url: str, cluster: str, analysis_run_id: int | None) -> dict:
    content, truncated, original_length = _snippet(result)
    provenance = {
        "title": result.title[:MAX_TITLE_LENGTH],
        # Do not retain a second, potentially tracking-bearing URL alongside
        # the canonical source locator.
        "url": normalized_url,
        "content": content,
        "score": result.score,
        "fetched_at": _provenance_timestamp(result.fetched_at),
        "source_metadata": json_normalize(dict(result.source_metadata or {})),
        "content_truncated": truncated,
        "original_content_length": original_length,
        "canonical_url": normalized_url,
        "source_cluster": cluster,
        "classification": _classification(),
    }
    if analysis_run_id is not None:
        provenance["analysis_run_id"] = analysis_run_id
    return provenance


def _append_provenance(source: EvidenceSource, item: dict) -> None:
    metadata = dict(source.source_metadata or {})
    entries = list(metadata.get("research_results", []))
    if item not in entries:
        entries.append(item)
    metadata["research_results"] = entries
    metadata["canonical_url"] = item["canonical_url"]
    source.source_metadata = metadata


def normalize_research_results(
    db: Session,
    *,
    project: Project,
    hypothesis: Hypothesis,
    results: Iterable[ResearchResult],
    analysis_run_id: int | None = None,
) -> NormalizationSummary:
    """Persist one source per canonical URL and one evidence item per domain.

    All raw provider records are retained in ``EvidenceSource.source_metadata``.
    Re-running normalization is idempotent for a hypothesis: it only augments
    provenance and reuses the existing evidence item for that source cluster.
    """
    if hypothesis.project_id != project.id:
        raise ValueError("Hypothesis does not belong to project")

    sources = list(db.scalars(select(EvidenceSource).where(EvidenceSource.project_id == project.id)))
    source_by_url = {canonical_url(source.url): source for source in sources if source.url and canonical_url(source.url)}
    representative_by_cluster: dict[str, EvidenceSource] = {}
    created_sources = skipped = 0

    for result in results:
        normalized_url = canonical_url(result.url)
        if not normalized_url:
            skipped += 1
            continue
        cluster = source_cluster(normalized_url)
        provenance = _provenance(result, normalized_url, cluster, analysis_run_id)
        source = source_by_url.get(normalized_url)
        if source is None:
            # The database identity is derived from the canonical URL so two
            # workers normalizing tracking variants converge on one source.
            identity_key = _source_identity(normalized_url)
            try:
                with db.begin_nested():
                    source = EvidenceSource(
                        project_id=project.id,
                        identity_key=identity_key,
                        name=result.title.strip()[:MAX_TITLE_LENGTH] or cluster,
                        url=normalized_url,
                        source_type="research",
                        source_metadata={"research_results": [provenance], "canonical_url": normalized_url},
                    )
                    db.add(source)
                    db.flush()
                created_sources += 1
            except IntegrityError:
                source = db.scalar(select(EvidenceSource).where(
                    EvidenceSource.project_id == project.id, EvidenceSource.identity_key == identity_key
                ))
                if source is None:
                    raise
                _append_provenance(source, provenance)
            source_by_url[normalized_url] = source
        else:
            _append_provenance(source, provenance)
        representative_by_cluster.setdefault(cluster, source)

    created_evidence = reused_evidence = 0
    for cluster, source in representative_by_cluster.items():
        evidence = db.scalar(select(Evidence).where(
            Evidence.normalization_hypothesis_id == hypothesis.id,
            Evidence.source_cluster == cluster,
        ))
        if evidence is None:
            provenance = (source.source_metadata or {}).get("research_results", [{}])[0]
            content = provenance.get("content") or provenance.get("title") or source.name
            classification = provenance.get("classification") or _classification()
            try:
                # The unique key is the concurrency backstop for the prior read.
                with db.begin_nested():
                    evidence = Evidence(
                        source=source,
                        normalization_hypothesis_id=hypothesis.id,
                        # The snippet is a candidate claim, not verified evidence.
                        content=content,
                        candidate_claim=content,
                        evidence_status="candidate",
                        verification_reason=classification["reason"],
                        direction=classification["direction"],
                        tier=classification["tier"],
                        category="research",
                        relevance=0.0,
                        source_quality=0.0,
                        source_cluster=cluster,
                        independent=True,
                    )
                    evidence.links.append(EvidenceLink(hypothesis=hypothesis, relation=classification["relation"]))
                    db.add(evidence)
                    db.flush()
                created_evidence += 1
            except IntegrityError:
                evidence = db.scalar(select(Evidence).where(
                    Evidence.normalization_hypothesis_id == hypothesis.id,
                    Evidence.source_cluster == cluster,
                ))
                if evidence is None:
                    raise
                reused_evidence += 1
        else:
            reused_evidence += 1

    return NormalizationSummary(created_sources, created_evidence, reused_evidence, skipped)
