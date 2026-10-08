import html
import json
from collections import Counter
from copy import deepcopy
from urllib.parse import urlsplit
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse, PlainTextResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    AnalysisRun, AuditEvent, Competitor, EconomicsModel, Evidence, EvidenceLink, EvidenceSource,
    ExperimentProposal, Hypothesis, ICPSegment, MarketEntity, MonetizationAssumption, Project, ProjectVerdict,
    RiskMapEntry, Verdict,
)
from app.db.session import get_db
from app.schemas.projects import ProjectCreate, ProjectHistoryEventRead, ProjectRead, ProjectReportRead
from app.services.audit import record_audit_event
from app.services.report_gaps import build_structured_report_gaps

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def create_project(project_in: ProjectCreate, db: Annotated[Session, Depends(get_db)]) -> Project:
    project = Project(**project_in.model_dump())
    db.add(project)
    db.flush()
    record_audit_event(
        db,
        project_id=project.id,
        event_type="project.created",
        entity_type="project",
        entity_id=project.id,
        payload={"name": project.name},
    )
    db.commit()
    db.refresh(project)
    return project


@router.get("", response_model=list[ProjectRead])
def list_projects(db: Annotated[Session, Depends(get_db)]) -> list[Project]:
    """Return projects in stable creation order for project pickers and dashboards."""
    return list(db.scalars(select(Project).order_by(Project.id)))


@router.get("/{project_id}", response_model=ProjectRead)
def get_project(project_id: int, db: Annotated[Session, Depends(get_db)]) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.get("/{project_id}/history", response_model=list[ProjectHistoryEventRead])
def project_history(project_id: int, db: Annotated[Session, Depends(get_db)]) -> list[AuditEvent]:
    """Return the requested project's chronological, UI-ready audit history."""
    if db.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return list(db.scalars(
        select(AuditEvent).where(AuditEvent.project_id == project_id).order_by(AuditEvent.created_at, AuditEvent.id)
    ))


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: int, db: Annotated[Session, Depends(get_db)]) -> Response:
    """Atomically remove a project and every project-owned record, including its audit trail.

    Audit events have a cascading foreign key to their project, so emitting a
    ``project.deleted`` event would create an event that cannot be retained.
    Deleting the aggregate in one transaction avoids both dangling audit rows
    and a partially deleted project when a constraint fails.
    """
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    try:
        db.delete(project)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _markdown_text(value: Any) -> str:
    """Render arbitrary stored data as inert Markdown text (never HTML)."""
    if value is None:
        return "—"
    if not isinstance(value, str):
        value = str(value)
    # Escape HTML first, then every Markdown punctuation character which can
    # introduce formatting, links, headings, lists, or code blocks.
    # Keep existing entities single-escaped so the print HTML escapes them a
    # second time without producing confusing &amp;amp; sequences.
    value = value.replace("<", "&lt;").replace(">", "&gt;")
    return "".join(f"\\{character}" if character in r"\\`*_[]()#+-=|{}.!" else character for character in value)


def _json_text(value: Any) -> str:
    return _markdown_text(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str))


def _localized_record_json_text(value: Any, language: str) -> str:
    """Render manual-record JSON with catalogued RU field names only."""
    if language == "ru" and isinstance(value, dict):
        value = {_RU_EXPORT_TEXT.get(str(key), str(key)): item for key, item in value.items()}
    return _json_text(value)


def _append_value(lines: list[str], label: str, value: Any) -> None:
    lines.append(f"- **{label}:** {_markdown_text(value)}")


def _safe_evidence_url(value: str | None) -> str | None:
    """Only publish web URLs; exports must never turn stored schemes into links."""
    if not value:
        return None
    parsed = urlsplit(value)
    return value if parsed.scheme in {"http", "https"} and parsed.netloc else None


def _redact_volatile_research(result: Any) -> Any:
    """Remove provider snippets from durable-run and verdict export snapshots."""
    if not isinstance(result, dict):
        return result
    redacted = deepcopy(result)
    for key in ("research_results", "market_findings", "market_snippets", "snippets"):
        redacted.pop(key, None)
    return redacted


def _sanitize_export_payload(value: Any, *, redact_research: bool = False) -> Any:
    """Recursively remove RU research material and unsafe URLs from exports."""
    if isinstance(value, list):
        return [_sanitize_export_payload(item, redact_research=redact_research) for item in value]
    if not isinstance(value, dict):
        return value

    sanitized: dict[str, Any] = {}
    for key, item in value.items():
        normalized_key = str(key).lower()
        if redact_research and any(token in normalized_key for token in ("research", "evidence", "snippet")):
            continue
        if normalized_key == "url" or normalized_key.endswith("_url") or normalized_key == "href":
            sanitized[key] = _safe_evidence_url(item) if isinstance(item, str) else None
        else:
            sanitized[key] = _sanitize_export_payload(item, redact_research=redact_research)
    return sanitized


_RU_EXPORT_TEXT = {
    "Decision First": "Решение в первую очередь", "Project Intake": "Параметры проекта",
    "Hypotheses": "Гипотезы", "Evidence Summary": "Сводка доказательств",
    "Latest Verdicts": "Последние вердикты", "Economics and Capital Plan": "Экономика и план капитала",
    "Experiments": "Эксперименты", "Project Verdict": "Вердикт проекта", "Analysis Runs": "Запуски анализа",
    "Structured Data Gaps": "Пробелы структурированных данных", "ProjectDecision": "Решение по проекту",
    "Statement": "Гипотеза", "Category": "Категория", "Status": "Статус", "Verdict": "Вердикт",
    "Rationale": "Обоснование", "Source": "Источник", "Content": "Содержание", "Direction": "Направление",
    "Tier": "Уровень", "Title": "Название", "Rule": "Правило", "Rules": "Правила", "Language": "Язык",
    "Description": "Описание", "Action": "Действие", "Decision rule": "Правило решения",
    "Market attractiveness": "Привлекательность рынка", "Market Attractiveness": "Привлекательность рынка",
    "Business viability": "Жизнеспособность бизнеса", "Business Viability": "Жизнеспособность бизнеса",
    "Capital recommendation": "Рекомендация по капиталу", "Capital Recommendation": "Рекомендация по капиталу",
    "Geography": "География", "Business type": "Тип бизнеса",
    "Budget": "Бюджет", "Deadline days": "Срок, дней", "Known facts": "Известные факты",
    "Importance": "Важность", "Total evidence": "Всего доказательств", "URL": "Ссылка",
    "Economics and Capital Plan": "Экономика и план капитала", "Formula version": "Версия формулы",
    "Total required": "Всего требуется", "Expected learning": "Ожидаемое обучение", "Unlock condition": "Условие разблокировки",
    "Hypothesis ID": "ID гипотезы", "Idea Summary": "Сводка идеи", "Success Conditions": "Условия успеха",
    "Failure Conditions / Kill Gates": "Условия провала / стоп-гейты", "Tested Hypotheses": "Проверенные гипотезы",
    "Market Findings (Candidates, Not Evidence)": "Рыночные наблюдения (кандидаты, не доказательства)",
    "Evidence Quality": "Качество доказательств", "Next Recommended Tests": "Следующие рекомендованные тесты",
    "Decisive Facts": "Решающие факты", "Unknowns": "Неизвестные данные", "Ranked Assumptions": "Ранжированные допущения",
    "Experiment Alternatives Comparison": "Сравнение альтернатив экспериментов", "Market, ICP, Competition, Monetization and Risks": "Рынок, ICP, конкуренция, монетизация и риски",
    "Report language": "Язык отчёта", "Analysis Runs": "Запуски анализа", "Created at": "Создан", "Completed at": "Завершён", "Inputs": "Входные данные", "Result": "Результат",
    "market": "рынок", "icp": "ICP", "competitor": "конкуренты", "monetization": "монетизация", "risk_map": "карта рисков",
    "target_customer_profile": "профиль целевого клиента", "buyer_role_and_job_to_be_done": "роль покупателя и задача", "segment_size_and_priority": "размер и приоритет сегмента",
    "market_definition": "определение рынка", "market_size_and_growth": "размер и рост рынка", "geography_specific_demand": "спрос в выбранной географии",
    "competitor_set": "набор конкурентов", "alternative_solutions": "альтернативные решения", "competitive_differentiation": "конкурентная дифференциация",
    "pricing_and_packaging": "ценообразование и упаковка", "willingness_to_pay": "готовность платить", "revenue_model_validation": "проверка модели выручки",
    "risk_register": "реестр рисков", "probability_and_impact": "вероятность и влияние", "mitigations_and_owners": "меры снижения и ответственные",
    "id": "ID", "project_id": "ID проекта", "provenance": "Происхождение", "source_reference": "Ссылка на источник", "created_at": "Создано",
    "name": "Название", "entity_type": "Тип сущности", "claim": "Утверждение", "verification_status": "Статус проверки",
    "competitor_type": "Тип конкурента", "positioning": "Позиционирование", "profile": "Профиль", "job_to_be_done": "Задача пользователя", "priority": "Приоритет",
    "assumption": "Допущение", "value": "Значение", "currency": "Валюта", "probability": "Вероятность", "impact": "Влияние", "mitigation": "Мера снижения", "owner": "Ответственный",
    "not_collected_as_structured_data": "не собрано как структурированные данные",
    "None.": "Нет данных.", "No ProjectDecision snapshot yet.": "Снимок решения по проекту пока отсутствует.",
    "No capital steps recorded.": "Этапы капитала не записаны.", "Unknown: no manually supplied structured records.": "Неизвестно: нет вручную введённых структурированных записей.",
}
_RU_EXPORT_ENUMS = {
    "queued": "в очереди", "running": "выполняется", "completed": "завершено", "failed": "ошибка",
    "proposed": "предложен", "approved": "одобрен", "stopped": "остановлен", "locked": "заблокирован",
    "unlocked": "разблокирован", "passed": "пройден", "supported": "подтверждено", "refuted": "опровергнуто",
    "inconclusive": "неопределённо", "unproven": "не подтверждено", "candidate": "кандидат",
    "verified": "проверено", "unknown": "неизвестно", "go": "запуск", "validate": "проверить", "no_go": "не запускать",
    "target_customer_profile": "профиль целевого клиента", "buyer_role_and_job_to_be_done": "роль покупателя и задача", "segment_size_and_priority": "размер и приоритет сегмента",
    "market_definition": "определение рынка", "market_size_and_growth": "размер и рост рынка", "geography_specific_demand": "спрос в выбранной географии",
    "competitor_set": "набор конкурентов", "alternative_solutions": "альтернативные решения", "competitive_differentiation": "конкурентная дифференциация",
    "pricing_and_packaging": "ценообразование и упаковка", "willingness_to_pay": "готовность платить", "revenue_model_validation": "проверка модели выручки",
    "risk_register": "реестр рисков", "probability_and_impact": "вероятность и влияние", "mitigations_and_owners": "меры снижения и ответственные",
    "not_collected_as_structured_data": "не собрано как структурированные данные",
}


_RU_EXPORT_DYNAMIC_HEADINGS = {
    "Hypothesis ": "Гипотеза ", "Evidence ": "Доказательство ",
    "Experiment ": "Эксперимент ", "Run ": "Запуск ",
}


def _ru_export_label(label: str) -> str:
    """Localize only catalogued export chrome, never persisted prose."""
    if label in _RU_EXPORT_TEXT:
        return _RU_EXPORT_TEXT[label]
    for source, target in _RU_EXPORT_DYNAMIC_HEADINGS.items():
        if label.startswith(source):
            return f"{target}{label[len(source):]}"
    return label


def _localize_export(lines: list[str], language: str) -> list[str]:
    """Localize every known Markdown heading and label structurally for RU."""
    if language != "ru":
        return lines
    localized: list[str] = []
    for line in lines:
        if line.startswith("#") and " " in line:
            marker, label = line.split(" ", 1)
            line = f"{marker} {_ru_export_label(label)}"
        elif "**" in line and ":**" in line:
            prefix, label_and_value = line.split("**", 1)
            label, value = label_and_value.split(":**", 1)
            line = f"{prefix}**{_ru_export_label(label.strip())}:**{value}"
        elif line in _RU_EXPORT_TEXT:
            line = _RU_EXPORT_TEXT[line]
        elif line.startswith("- "):
            # Fallback messages are list-prefixed in the Markdown source.
            # Localize the chrome without touching persisted record prose.
            fallback = line[2:]
            if fallback in _RU_EXPORT_TEXT:
                line = f"- {_RU_EXPORT_TEXT[fallback]}"
        localized.append(line)
    return localized


def _project_report(project_id: int, db: Session) -> dict[str, Any]:
    """Build the current, project-scoped decision snapshot used by both JSON views."""
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    hypotheses = list(db.scalars(
        select(Hypothesis).where(Hypothesis.project_id == project_id).order_by(Hypothesis.id)
    ))
    sources = list(db.scalars(
        select(EvidenceSource).where(EvidenceSource.project_id == project_id).order_by(EvidenceSource.id)
    ))
    source_ids = [source.id for source in sources]
    evidence = list(db.scalars(select(Evidence).where(Evidence.source_id.in_(source_ids)).order_by(Evidence.id))) if source_ids else []
    evidence_ids = [item.id for item in evidence]
    hypothesis_ids = [hypothesis.id for hypothesis in hypotheses]
    links = list(db.scalars(select(EvidenceLink).where(
        EvidenceLink.hypothesis_id.in_(hypothesis_ids), EvidenceLink.evidence_id.in_(evidence_ids)
    ).order_by(EvidenceLink.id))) if hypothesis_ids and evidence_ids else []

    # A verdict is a snapshot. Keep only the most recent one for each project
    # hypothesis so this report cannot mix decisions from separate runs.
    latest_verdict_by_hypothesis: dict[int, Verdict] = {}
    for verdict in db.scalars(
        select(Verdict).join(Hypothesis, Verdict.hypothesis_id == Hypothesis.id)
        .where(Hypothesis.project_id == project_id)
        .order_by(Hypothesis.id, Verdict.created_at.desc(), Verdict.id.desc())
    ):
        latest_verdict_by_hypothesis.setdefault(verdict.hypothesis_id, verdict)
    latest_verdicts = [latest_verdict_by_hypothesis[hypothesis.id] for hypothesis in hypotheses
                       if hypothesis.id in latest_verdict_by_hypothesis]

    runs = list(db.scalars(select(AnalysisRun).where(
        AnalysisRun.project_id == project_id
    ).order_by(AnalysisRun.id)))
    economics_models = list(db.scalars(select(EconomicsModel).where(
        EconomicsModel.project_id == project_id
    ).order_by(EconomicsModel.id)))
    latest_run = max(runs, key=lambda run: (run.created_at, run.id), default=None)
    latest_economics = max(economics_models, key=lambda model: (model.created_at, model.id), default=None)
    latest_project_verdict = db.scalar(select(ProjectVerdict).where(
        ProjectVerdict.project_id == project_id
    ).order_by(ProjectVerdict.created_at.desc(), ProjectVerdict.id.desc()).limit(1))
    experiments = list(db.scalars(select(ExperimentProposal).where(
        ExperimentProposal.project_id == project_id
    ).order_by(ExperimentProposal.id)))
    audit_events = list(db.scalars(select(AuditEvent).where(
        AuditEvent.project_id == project_id
    ).order_by(AuditEvent.created_at, AuditEvent.id)))
    strategy_records = {
        "market": list(db.scalars(select(MarketEntity).where(MarketEntity.project_id == project_id).order_by(MarketEntity.id))),
        "competitor": list(db.scalars(select(Competitor).where(Competitor.project_id == project_id).order_by(Competitor.id))),
        "icp": list(db.scalars(select(ICPSegment).where(ICPSegment.project_id == project_id).order_by(ICPSegment.id))),
        "monetization": list(db.scalars(select(MonetizationAssumption).where(MonetizationAssumption.project_id == project_id).order_by(MonetizationAssumption.id))),
        "risk_map": list(db.scalars(select(RiskMapEntry).where(RiskMapEntry.project_id == project_id).order_by(RiskMapEntry.id))),
    }
    # One builder powers report and verdict gap disclosure; only attributable
    # manual records overlay an otherwise explicit unknown.
    structured_gaps = build_structured_report_gaps(
        project.language, jsonable_encoder(strategy_records)
    )
    project_verdict = None
    decisive_facts: list[Any] = []
    unknowns: list[Any] = []
    ranked_assumptions: list[Any] = []
    if latest_project_verdict is not None:
        # Flatten the immutable engine result into the report while retaining
        # snapshot identity and creation time for auditability.
        verdict_result = _redact_volatile_research(latest_project_verdict.result or {})
        project_verdict = {
            "id": latest_project_verdict.id,
            "project_id": latest_project_verdict.project_id,
            "economics_snapshot_id": latest_project_verdict.economics_model_id,
            "created_at": latest_project_verdict.created_at,
            **verdict_result,
            **structured_gaps,
        }
        decisive_facts = verdict_result.get("decisive_facts", [])
        unknowns = verdict_result.get("unknowns", [])
        ranked_assumptions = verdict_result.get("ranked_assumptions", [])

    report = jsonable_encoder({
        "format_version": "v1.1",
        "project": project,
        "latest_run": latest_run,
        # Kept for backward-compatible full exports; consumers wanting a
        # one-run decision view should use the singular fields above.
        "analysis_runs": runs,
        "economics_models": economics_models,
        "hypotheses": hypotheses,
        "verdicts": latest_verdicts,
        "evidence_sources": sources,
        "evidence": evidence,
        "evidence_links": links,
        "latest_economics": latest_economics,
        "experiments": experiments,
        "project_verdict": project_verdict,
        "decisive_facts": decisive_facts,
        "unknowns": unknowns,
        "ranked_assumptions": ranked_assumptions,
        "audit_events": audit_events,
        **structured_gaps,
    })
    # AnalysisRun objects are encoded above; redact export/report payloads
    # without changing durable database snapshots.
    for run in report["analysis_runs"]:
        run["result"] = _redact_volatile_research(run.get("result"))
    if report["latest_run"]:
        report["latest_run"]["result"] = _redact_volatile_research(report["latest_run"].get("result"))
    return report


@router.get("/{project_id}/report", response_model=ProjectReportRead)
def get_project_report(project_id: int, db: Annotated[Session, Depends(get_db)]) -> dict[str, Any]:
    """Return one current decision-ready report for exactly one project."""
    return _project_report(project_id, db)


def _localize_russian_gap_presentation(value: Any) -> Any:
    """Translate only catalogued gap display values in portable RU exports."""
    if isinstance(value, list):
        return [_localize_russian_gap_presentation(item) for item in value]
    if not isinstance(value, dict):
        return value
    return {
        key: (
            _RU_EXPORT_ENUMS.get(item, item)
            if key in {"field", "reason"} and isinstance(item, str)
            else _localize_russian_gap_presentation(item)
        )
        for key, item in value.items()
    }


@router.get("/{project_id}/export/json", response_model=ProjectReportRead)
def export_project_json(project_id: int, db: Annotated[Session, Depends(get_db)]) -> dict[str, Any]:
    """Export a portable report with URL sanitization and RU research redaction."""
    report = _project_report(project_id, db)
    report = _sanitize_export_payload(report, redact_research=report["project"].get("language") == "ru")
    return _localize_russian_gap_presentation(report) if report["project"].get("language") == "ru" else report


@router.get("/{project_id}/export/html", response_class=HTMLResponse)
def export_project_html(project_id: int, db: Annotated[Session, Depends(get_db)]) -> HTMLResponse:
    """Safe print-ready export.

    Stored user content is HTML-escaped and displayed as text, rather than
    interpreted as markup, so opening this endpoint cannot execute report data.
    Browsers can save the resulting document as a PDF via their print dialog.
    """
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    markdown = export_project_markdown(project_id, db).body.decode("utf-8")
    # Markdown escapes are presentation syntax; the print view should not
    # display those escapes around ordinary parentheses.
    markdown = markdown.replace("\\(", "(").replace("\\)", ")")
    print_label = "Печать / Сохранить PDF" if project.language == "ru" else "Print / Save as PDF"
    title = "Отчёт по проекту" if project.language == "ru" else "Project report"
    document = f'''<!doctype html><html lang="{project.language}"><head><meta charset="utf-8"><title>{title}</title><style>
body{{font:14px/1.5 system-ui,sans-serif;color:#172033;margin:32px auto;max-width:900px}}pre{{white-space:pre-wrap;word-break:break-word;font:13px/1.55 ui-monospace,SFMono-Regular,monospace}}@page{{margin:16mm}}@media print{{body{{margin:0}}.no-print{{display:none}}}}
</style></head><body><button class="no-print" onclick="window.print()">{print_label}</button><pre>''' + html.escape(markdown) + "</pre></body></html>"
    return HTMLResponse(document, headers={"Content-Disposition": "inline; filename=project-report.html", "X-Content-Type-Options": "nosniff"})


@router.get("/{project_id}/export/markdown", response_class=PlainTextResponse)
def export_project_markdown(project_id: int, db: Annotated[Session, Depends(get_db)]) -> PlainTextResponse:
    """Export only the requested project's data as safe, portable Markdown."""
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    hypotheses = list(db.scalars(
        select(Hypothesis).where(Hypothesis.project_id == project_id).order_by(Hypothesis.id)
    ))
    evidence_rows = db.execute(
        select(Evidence, EvidenceSource)
        .join(EvidenceSource, Evidence.source_id == EvidenceSource.id)
        .where(EvidenceSource.project_id == project_id)
        .order_by(Evidence.id)
    ).all()
    runs = list(db.scalars(
        select(AnalysisRun).where(AnalysisRun.project_id == project_id).order_by(AnalysisRun.id)
    ))
    latest_economics = db.scalar(
        select(EconomicsModel).where(EconomicsModel.project_id == project_id).order_by(EconomicsModel.id.desc())
    )
    experiments = list(db.scalars(
        select(ExperimentProposal).where(ExperimentProposal.project_id == project_id).order_by(ExperimentProposal.id)
    ))
    latest_project_verdict = db.scalar(
        select(ProjectVerdict).where(ProjectVerdict.project_id == project_id)
        .order_by(ProjectVerdict.created_at.desc(), ProjectVerdict.id.desc()).limit(1)
    )

    # Fetching all project verdicts in newest-first order makes the selection
    # deterministic even when records share a timestamp.
    latest_verdicts: dict[int, Verdict] = {}
    verdict_rows = db.scalars(
        select(Verdict)
        .join(Hypothesis, Verdict.hypothesis_id == Hypothesis.id)
        .where(Hypothesis.project_id == project_id)
        .order_by(Hypothesis.id, Verdict.created_at.desc(), Verdict.id.desc())
    )
    for verdict in verdict_rows:
        latest_verdicts.setdefault(verdict.hypothesis_id, verdict)

    lines = [f"# {_markdown_text(project.name)}", "", "## Decision First"]
    if latest_project_verdict:
        decision_result = latest_project_verdict.result or {}
        _append_value(lines, "ProjectDecision", decision_result.get("decision", latest_project_verdict.decision))
        _append_value(lines, "Action", decision_result.get("action"))
        _append_value(lines, "Decision rule", decision_result.get("rule"))
        _append_value(lines, "Market attractiveness", (decision_result.get("market_attractiveness") or {}).get("status"))
        _append_value(lines, "Business viability", (decision_result.get("business_viability") or {}).get("status"))
        _append_value(lines, "Capital recommendation", (decision_result.get("capital_recommendation") or {}).get("recommendation"))
    else:
        lines.append("- No ProjectDecision snapshot yet.")
    lines.extend(["", "## Project Intake"])
    _append_value(lines, "Description", project.description)
    _append_value(lines, "Geography", project.geography)
    _append_value(lines, "Business type", project.business_type)
    _append_value(lines, "Budget", project.budget)
    _append_value(lines, "Deadline days", project.deadline_days)
    _append_value(lines, "Language", project.language)
    lines.append("- **Known facts:**")
    if project.known_facts:
        lines.extend(f"  - {_markdown_text(fact)}" for fact in project.known_facts)
    else:
        lines.append("  - —")

    lines.extend(["", "## Hypotheses"])
    if hypotheses:
        for hypothesis in hypotheses:
            lines.extend([
                f"### Hypothesis {hypothesis.id}",
                f"- **Statement:** {_markdown_text(hypothesis.statement)}",
                f"- **Category:** {_markdown_text(hypothesis.category)}",
                f"- **Importance:** {hypothesis.importance}",
                f"- **Status:** {_markdown_text(hypothesis.status)}",
            ])
    else:
        lines.append("None.")

    direction_counts = Counter(evidence.direction for evidence, _source in evidence_rows)
    lines.extend(["", "## Evidence Summary", f"- **Total evidence:** {len(evidence_rows)}"])
    for direction, count in sorted(direction_counts.items()):
        lines.append(f"- **{_markdown_text(direction)}:** {count}")
    if evidence_rows:
        for evidence, source in evidence_rows:
            lines.extend([
                f"### Evidence {evidence.id}",
                f"- **Source:** {_markdown_text(source.name if project.language != 'ru' else 'Источник')}",
                f"- **URL:** {_markdown_text(_safe_evidence_url(source.url))}",
                f"- **Content:** {_markdown_text(evidence.content if project.language != 'ru' else 'Содержание скрыто в RU')}",
                f"- **Direction:** {_markdown_text(evidence.direction)}",
                f"- **Tier:** {_markdown_text(evidence.tier)}",
                f"- **Category:** {_markdown_text(evidence.category)}",
            ])
    else:
        lines.append("None.")

    lines.extend(["", "## Latest Verdicts"])
    if latest_verdicts:
        for hypothesis in hypotheses:
            verdict = latest_verdicts.get(hypothesis.id)
            if verdict is not None:
                lines.extend([
                    f"### Hypothesis {hypothesis.id}",
                    f"- **Verdict:** {_markdown_text(verdict.verdict)}",
                    f"- **Rationale:** {_markdown_text(verdict.rationale)}",
                ])
    else:
        lines.append("None.")

    lines.extend(["", "## Economics and Capital Plan"])
    if latest_economics:
        economics_inputs = latest_economics.economics_inputs or {}
        capital_plan = (latest_economics.result or {}).get("capital_plan", {})
        _append_value(lines, "Formula version", economics_inputs.get("formula_version", "unknown"))
        _append_value(lines, "Total required", f"{capital_plan.get('total_required', 0)} {capital_plan.get('currency', '')}".strip())
        steps = capital_plan.get("steps", [])
        if steps:
            for step in steps:
                lines.append(f"- **{_markdown_text(step.get('name'))}:** {_markdown_text(step.get('amount'))} {_markdown_text(capital_plan.get('currency'))}")
                _append_value(lines, "  Expected learning", step.get("expected_learning"))
                _append_value(lines, "  Unlock condition", step.get("unlock_condition"))
        else:
            lines.append("- No capital steps recorded.")
    else:
        lines.append("None.")

    lines.extend(["", "## Experiments"])
    if experiments:
        for experiment in experiments:
            lines.extend([
                f"### Experiment {experiment.id}",
                f"- **Title:** {_markdown_text(experiment.title)}",
                f"- **Status:** {_markdown_text(experiment.status)}",
                f"- **Hypothesis ID:** {_markdown_text(experiment.hypothesis_id)}",
                f"- **Rules:** {_json_text(experiment.rules)}",
            ])
    else:
        lines.append("None.")

    lines.extend(["", "## Project Verdict"])
    if latest_project_verdict:
        result = {**build_structured_report_gaps(project.language), **_redact_volatile_research(latest_project_verdict.result or {})}
        _append_value(lines, "ProjectDecision", result.get("decision", latest_project_verdict.decision))
        _append_value(lines, "Verdict", latest_project_verdict.verdict)
        _append_value(lines, "Rule", result.get("rule"))
        for heading, key in (("Idea Summary", "idea_summary"), ("Success Conditions", "success_conditions"),
                             ("Failure Conditions / Kill Gates", "failure_conditions"), ("Tested Hypotheses", "tested_hypotheses"),
                             ("Market Findings (Candidates, Not Evidence)", "market_findings"),
                             ("Evidence Quality", "evidence_quality"), ("Next Recommended Tests", "next_recommended_tests"),
                             ("Decisive Facts", "decisive_facts"), ("Unknowns", "unknowns"),
                             ("Ranked Assumptions", "ranked_assumptions"), ("Market Attractiveness", "market_attractiveness"),
                             ("Business Viability", "business_viability"), ("Experiment Alternatives Comparison", "experiment_comparison"),
                             ("Capital Recommendation", "capital_recommendation")): 
            lines.append(f"### {heading}")
            values = result.get(key, [])
            if values:
                if isinstance(values, list):
                    lines.extend(f"- {_json_text(value)}" for value in values)
                else:
                    lines.append(f"- {_json_text(values)}")
            else:
                lines.append("- —")
    else:
        lines.append("None.")

    structured_report = _project_report(project_id, db)
    lines.extend(["", "## Market, ICP, Competition, Monetization and Risks"])
    for section in ("market", "icp", "competitor", "monetization", "risk_map"):
        value = structured_report[section]
        lines.append(f"### {_markdown_text(section)}")
        if value["status"] == "collected":
            for record in value["records"]:
                lines.append(f"- {_localized_record_json_text(record, project.language)}")
        else:
            lines.append("- Unknown: no manually supplied structured records.")
    lines.extend(["", "## Structured Data Gaps"])
    _append_value(lines, "Report language", structured_report["language_metadata"]["code"])
    for gap in structured_report["data_gaps"]:
        section = _RU_EXPORT_ENUMS.get(gap["section"], gap["section"]) if project.language == "ru" else gap["section"]
        field = _RU_EXPORT_ENUMS.get(gap["field"], gap["field"]) if project.language == "ru" else gap["field"]
        reason = _RU_EXPORT_ENUMS.get(gap["reason"], gap["reason"]) if project.language == "ru" else gap["reason"]
        lines.append(f"- **{_markdown_text(section)}.{_markdown_text(field)}:** {_markdown_text(gap['status'])} ({_markdown_text(reason)})")

    lines.extend(["", "## Analysis Runs"])
    if runs:
        for run in runs:
            lines.extend([
                f"### Run {run.id}",
                f"- **Status:** {_markdown_text(run.status)}",
                f"- **Created at:** {_markdown_text(run.created_at.isoformat())}",
                f"- **Completed at:** {_markdown_text(run.completed_at.isoformat() if run.completed_at else None)}",
                f"- **Inputs:** {_json_text(run.inputs)}",
                f"- **Result:** {_json_text(_redact_volatile_research(run.result))}",
            ])
    else:
        lines.append("None.")

    return PlainTextResponse("\n".join(_localize_export(lines, project.language)) + "\n", media_type="text/markdown")
