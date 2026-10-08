"""Deterministic roll-up of hypothesis verdicts into a project decision."""
from __future__ import annotations

from enum import Enum
from typing import Any, Iterable, Literal


UNKNOWN = "unknown"


class ProjectDecision(str, Enum):
    """Action to take; it is not a hypothesis/project evidence verdict."""
    GO = "GO"
    VALIDATE = "VALIDATE"
    NO_GO = "NO_GO"

from app.services.report_gaps import build_structured_report_gaps


class ProjectVerdictEngine:
    """Apply explicit, stable gates to the latest project-level inputs.

    The engine only consumes JSON-safe snapshots.  Database selection and
    persistence deliberately live in the API layer, keeping the decision
    reproducible from the stored input snapshot.
    """

    evidence_coverage_required = 25
    high_priority = 0.7

    def evaluate(
        self,
        hypotheses: Iterable[dict[str, Any]],
        economics: dict[str, Any] | None,
        language: Literal["en", "ru"] = "en",
        *,
        intake: dict[str, Any] | None = None,
        research_results: Iterable[dict[str, Any]] = (),
        experiment_results: Iterable[dict[str, Any]] = (),
        market_context: dict[str, Any] | None = None,
        capital_plan: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        items = sorted(list(hypotheses), key=lambda item: item["hypothesis_id"])
        evaluated = [item for item in items if item.get("verdict") is not None]
        unknowns: list[str] = []
        if not items:
            unknowns.append("no_hypotheses")
        if len(evaluated) != len(items):
            unknowns.append("missing_hypothesis_verdicts")
        if not evaluated:
            unknowns.append("no_hypothesis_verdicts")
        if not evaluated or all("no_evidence" in item.get("unknowns", []) for item in evaluated):
            unknowns.append("no_evidence")

        total_importance = sum(float(item["importance"]) for item in evaluated)
        coverage = round(
            sum(float(item["importance"]) * int(item["coverage"]) for item in evaluated) / total_importance
        ) if total_importance else 0
        if coverage < self.evidence_coverage_required:
            unknowns.append("insufficient_evidence_coverage")

        decisive_facts = self._decisive_facts(evaluated)
        for item in evaluated:
            unknowns.extend(item.get("unknowns", []))
        unknowns = list(dict.fromkeys(unknowns))

        kill_gates = self._kill_gates(evaluated, economics)
        economics_summary, economics_unknowns = self._economics_summary(economics)
        unknowns.extend(item for item in economics_unknowns if item not in unknowns)
        unresolved_critical = self._unresolved_critical(items)
        if unresolved_critical:
            unknowns.append("unproven_blocking_or_fatal_hypothesis")

        if kill_gates:
            verdict, rule = "NO-GO-FOR-NOW", "kill_gate_triggered"
        elif unresolved_critical:
            verdict, rule = "UNPROVEN", "blocking_or_fatal_hypothesis_unproven"
        elif not evaluated or len(evaluated) != len(items) or coverage < self.evidence_coverage_required:
            verdict, rule = "UNPROVEN", "insufficient_project_evidence"
        elif all(item["verdict"] == "PROMISING" for item in evaluated) and economics_summary["status"] == "viable":
            verdict, rule = "PROMISING", "all_hypotheses_supported_and_economics_viable"
        elif any(item["verdict"] == "WEAK" for item in evaluated):
            verdict, rule = "WEAK", "hypothesis_portfolio_contains_weak_assumption"
        else:
            verdict, rule = "UNPROVEN", "inconclusive_hypothesis_portfolio"

        experiments = sorted(list(experiment_results), key=lambda item: int(item.get("id", 0)))
        research = sorted(
            [item for item in research_results if isinstance(item, dict)],
            key=lambda item: (str(item.get("url", "")), str(item.get("title", ""))),
        )
        tested_hypotheses = [self._hypothesis_summary(item) for item in evaluated]
        evidence_quality = self._evidence_quality(evaluated, research)
        failure_conditions = kill_gates or self._failure_conditions(evaluated, economics_summary)
        return {
            "verdict": verdict,
            "decision": self._decision(verdict).value,
            "action": self._action(verdict),
            "rule": rule,
            "evidence_coverage": coverage,
            "hypothesis_verdicts": tested_hypotheses,
            "idea_summary": self._idea_summary(intake or {}, items),
            "success_conditions": self._success_conditions(evaluated, economics_summary, experiments),
            "failure_conditions": failure_conditions,
            "tested_hypotheses": tested_hypotheses,
            "market_findings": self._market_findings(research),
            "evidence_quality": evidence_quality,
            "next_recommended_tests": self._next_tests(items, economics_summary, experiments),
            "economics": economics_summary,
            "decisive_facts": decisive_facts,
            "unknowns": unknowns,
            "kill_gates": kill_gates,
            "unresolved_critical_hypotheses": unresolved_critical,
            "ranked_assumptions": self._ranked_assumptions(items),
            # Keep demand/competition signals separate from the ability to
            # execute profitably; neither section silently upgrades unknowns.
            "market_attractiveness": self._market_attractiveness(market_context or {}, research),
            "business_viability": self._business_viability(economics_summary, items, market_context or {}),
            "experiment_comparison": self._experiment_comparison(experiments),
            "capital_recommendation": self._capital_recommendation(capital_plan, economics),
            **build_structured_report_gaps(language),
        }

    def _kill_gates(self, items: list[dict[str, Any]], economics: dict[str, Any] | None) -> list[dict[str, Any]]:
        gates = [
            {
                "gate": "high_priority_hypothesis_no_go",
                "hypothesis_id": item["hypothesis_id"],
                "reason": "A high-priority hypothesis has a NO-GO-FOR-NOW verdict.",
            }
            for item in items
            if item["verdict"] == "NO-GO-FOR-NOW" and float(item["importance"]) >= self.high_priority
        ]
        if economics:
            inputs_by_name = {
                item.get("name", "base"): item
                for item in economics.get("inputs", {}).get("scenarios", [])
            }
            for scenario in economics.get("result", {}).get("scenarios", []):
                metrics = scenario.get("metrics", {})
                ltv = metrics.get("ltv_simple")
                cac = inputs_by_name.get(scenario.get("name", "base"), {}).get("cac")
                if ltv is not None and cac not in (None, 0) and ltv < cac:
                    gates.append({
                        "gate": "economics_ltv_below_cac",
                        "scenario": scenario.get("name", "base"),
                        "reason": "Latest economics snapshot has LTV below CAC.",
                    })
        return gates

    @staticmethod
    def _economics_summary(economics: dict[str, Any] | None) -> tuple[dict[str, Any], list[str]]:
        if economics is None:
            return {"snapshot_id": None, "status": "missing", "reliability": "INSUFFICIENT_CRITICAL_INPUTS", "unknowns": ["no_economics_snapshot"]}, ["no_economics_snapshot"]
        result = economics.get("result", {})
        unknowns = list(result.get("unknowns", []))
        reliability = economics.get("reliability") or result.get("reliability")
        # Legacy snapshots did not record reliability.  Treat absent decision
        # inputs conservatively rather than promoting an incomplete model.
        if reliability is None:
            scenarios = result.get("scenarios", [])
            reliability = "RELIABLE" if scenarios and all(
                item.get("metrics", {}).get("ltv_simple") is not None and "months_to_payback" in item.get("metrics", {})
                for item in scenarios
            ) else "INSUFFICIENT_CRITICAL_INPUTS"
        if reliability != "RELIABLE":
            unknowns.append("insufficient_critical_economics_inputs")
        return {
            "snapshot_id": economics["snapshot_id"],
            "status": "viable" if not unknowns and reliability == "RELIABLE" else "incomplete",
            "reliability": reliability,
            "unknowns": list(dict.fromkeys(unknowns)),
        }, list(dict.fromkeys(unknowns))

    @staticmethod
    def _unresolved_critical(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {"hypothesis_id": item["hypothesis_id"], "criticality": item.get("criticality", "NORMAL"), "is_blocking": bool(item.get("is_blocking", False))}
            for item in items
            if (bool(item.get("is_blocking", False)) or item.get("criticality") == "FATAL")
            and item.get("verdict") != "PROMISING"
        ]

    @staticmethod
    def _decision(verdict: str) -> ProjectDecision:
        if verdict == "PROMISING":
            return ProjectDecision.GO
        if verdict == "NO-GO-FOR-NOW":
            return ProjectDecision.NO_GO
        return ProjectDecision.VALIDATE

    @staticmethod
    def _action(verdict: str) -> str:
        return {"PROMISING": "proceed", "NO-GO-FOR-NOW": "stop_or_reframe"}.get(verdict, "validate_critical_assumptions")

    @staticmethod
    def _idea_summary(intake: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Any]:
        description = intake.get("description") or UNKNOWN
        hypotheses = [item["statement"] for item in items]
        return {
            "name": intake.get("name") or UNKNOWN,
            "description": description,
            "geography": intake.get("geography") or UNKNOWN,
            "business_type": intake.get("business_type") or UNKNOWN,
            "known_facts": list(intake.get("known_facts") or []),
            "hypotheses": hypotheses,
            "status": "known" if description != UNKNOWN or hypotheses else UNKNOWN,
        }

    @staticmethod
    def _market_findings(research: list[dict[str, Any]]) -> list[dict[str, Any]]:
        # Provider snippets are leads only. They must never be represented as
        # evidence until an explicit review creates non-E0 evidence.
        return [{
            "title": item.get("title") or UNKNOWN,
            "url": item.get("url") or UNKNOWN,
            "snippet": str(item.get("content") or "")[:500],
            "status": "candidate",
            "evidence_status": "unverified_search_snippet",
        } for item in research]

    @staticmethod
    def _evidence_quality(items: list[dict[str, Any]], research: list[dict[str, Any]]) -> dict[str, Any]:
        coverage = round(sum(int(item.get("coverage", 0)) for item in items) / len(items)) if items else 0
        return {
            "status": "unknown" if not items or all("no_evidence" in item.get("unknowns", []) for item in items) else "measured",
            "hypotheses_evaluated": len(items),
            "average_coverage": coverage,
            "unverified_market_candidates": len(research),
            "note": "Search snippets are candidates, not confirmed evidence.",
        }

    @staticmethod
    def _success_conditions(items: list[dict[str, Any]], economics: dict[str, Any], experiments: list[dict[str, Any]]) -> list[dict[str, Any]]:
        conditions = [{"condition": "Economics are viable", "status": economics["status"], "source": "economics"}]
        conditions.extend({"condition": f"Hypothesis {item['hypothesis_id']} is supported", "status": item["verdict"], "source": "evidence"} for item in items)
        conditions.extend({"condition": f"Experiment {item.get('id', UNKNOWN)} meets forecast", "status": item.get("outcome", UNKNOWN), "source": "experiment"} for item in experiments)
        return conditions

    @staticmethod
    def _failure_conditions(items: list[dict[str, Any]], economics: dict[str, Any]) -> list[dict[str, Any]]:
        conditions = [{"gate": "economics_incomplete", "status": "unknown", "reason": "Economics snapshot is missing or incomplete."}] if economics["status"] != "viable" else []
        conditions.extend({"gate": "hypothesis_weak", "hypothesis_id": item["hypothesis_id"], "reason": "Hypothesis is not yet supported."} for item in items if item["verdict"] in {"WEAK", "UNPROVEN"})
        return conditions

    @staticmethod
    def _next_tests(items: list[dict[str, Any]], economics: dict[str, Any], experiments: list[dict[str, Any]]) -> list[dict[str, Any]]:
        tests = []
        for item in items:
            if item.get("verdict") != "PROMISING":
                tests.append({"hypothesis_id": item["hypothesis_id"], "status": "unknown", "test": "Run 10 problem interviews with the target segment", "reason": "Validate the highest-risk unsupported hypothesis."})
        if economics["status"] != "viable":
            tests.append({"hypothesis_id": None, "status": "unknown", "test": "Enter price, variable cost, churn, CAC and fixed-cost assumptions; calculate economics", "reason": "Unit economics are unknown."})
        if not experiments:
            tests.append({"hypothesis_id": None, "status": "unknown", "test": "Run a landing-page or interview experiment with a pre-set pass/fail threshold", "reason": "No experiment result is available."})
        return tests

    @staticmethod
    def _hypothesis_summary(item: dict[str, Any]) -> dict[str, Any]:
        return {key: item[key] for key in ("hypothesis_id", "verdict", "importance", "coverage", "support_score", "rule", "criticality", "is_blocking") if key in item}

    @staticmethod
    def _market_attractiveness(context: dict[str, Any], research: list[dict[str, Any]]) -> dict[str, Any]:
        entities = context.get("market_entities", [])
        competitors = context.get("competitors", [])
        icp = context.get("icp_segments", [])
        signals = len(entities) + len(icp)
        return {
            "status": "assessed" if signals else "unknown",
            "summary": "Manual market and ICP records are available." if signals else "No structured market or ICP evidence has been collected.",
            "market_signals": len(entities),
            "icp_segments": len(icp),
            "competitors": len(competitors),
            "unverified_research_candidates": len(research),
            "unknowns": [] if signals else ["market_attractiveness_not_measured"],
        }

    @staticmethod
    def _business_viability(economics: dict[str, Any], items: list[dict[str, Any]], context: dict[str, Any]) -> dict[str, Any]:
        supported = sum(item.get("verdict") == "PROMISING" for item in items)
        monetization = context.get("monetization_assumptions", [])
        return {
            "status": "viable" if economics["status"] == "viable" else "unknown",
            "economics_status": economics["status"],
            "economics_reliability": economics["reliability"],
            "supported_hypotheses": supported,
            "hypotheses_assessed": len(items),
            "monetization_assumptions": len(monetization),
            "unknowns": list(economics.get("unknowns", [])),
        }

    @staticmethod
    def _experiment_comparison(experiments: list[dict[str, Any]]) -> dict[str, Any]:
        selected = [item for item in experiments if item.get("status") not in {"rejected", "stopped"}]
        alternatives = []
        for item in experiments:
            if item in selected:
                continue
            alternatives.append({
                "id": item.get("id"), "title": item.get("title", UNKNOWN),
                "status": item.get("status", UNKNOWN),
                "why_not": item.get("rationale") or "Not selected because it was rejected or stopped.",
            })
        return {
            "selected": selected,
            "alternatives": alternatives,
            "why_not_alternatives": alternatives,
            "status": "compared" if experiments else "unknown",
        }

    @staticmethod
    def _capital_recommendation(plan: dict[str, Any] | None, economics: dict[str, Any]) -> dict[str, Any]:
        if plan:
            unlocked = [gate for gate in plan.get("gates", []) if gate.get("status") == "UNLOCKED"]
            return {
                "status": "ready" if unlocked else "gated",
                "currency": plan.get("currency", "USD"),
                "available_budget": plan.get("available_budget"),
                "recommended_spend": plan.get("recommended_spend", 0),
                "gates": plan.get("gates", []),
                "recommendation": "Release only unlocked gate spend." if unlocked else "Do not release capital until the first gate is unlocked.",
            }
        return {
            "status": "unknown", "currency": None, "available_budget": None,
            "recommended_spend": 0, "gates": [],
            "recommendation": "Create a gated capital plan after validating economics.",
            "unknowns": ["no_durable_capital_plan", *((economics or {}).get("unknowns", []))],
        }

    @staticmethod
    def _decisive_facts(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        facts = []
        for item in items:
            for fact in item.get("decisive_facts", []):
                facts.append({"hypothesis_id": item["hypothesis_id"], **fact})
        return sorted(facts, key=lambda fact: (-float(fact.get("weight", 0)), fact["hypothesis_id"], str(fact.get("source_cluster", ""))))[:5]

    @staticmethod
    def _ranked_assumptions(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        risk = {"NO-GO-FOR-NOW": 3, "WEAK": 2, "UNPROVEN": 1, None: 1, "PROMISING": 0}
        ranked = [
            {
                "hypothesis_id": item["hypothesis_id"],
                "statement": item["statement"],
                "importance": item["importance"],
                "criticality": item.get("criticality", "NORMAL"),
                "is_blocking": bool(item.get("is_blocking", False)),
                "verdict": item.get("verdict"),
                "coverage": item.get("coverage", 0),
                "unknowns": item.get("unknowns", []),
            }
            for item in items
        ]
        return sorted(ranked, key=lambda item: (-risk[item["verdict"]], -float(item["importance"]), item["hypothesis_id"]))


def evaluate_project_verdict(
    hypotheses: Iterable[dict[str, Any]],
    economics: dict[str, Any] | None,
    language: Literal["en", "ru"] = "en",
    **context: Any,
) -> dict[str, Any]:
    return ProjectVerdictEngine().evaluate(hypotheses, economics, language, **context)
