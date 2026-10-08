"""Transparent market attractiveness assessment, never a single magic score."""
DIMENSIONS = ("problem_severity","problem_frequency","buyer_urgency","existing_spend","market_activity","competitive_intensity","growth_signal","switching_friction","timing")
def assess_market(*, observations: dict[str, dict] | None = None) -> dict:
    observations = observations or {}
    dimensions = {}
    unknowns=[]
    for name in DIMENSIONS:
        item=observations.get(name, {})
        dimensions[name]={"value":item.get("value","UNKNOWN"),"evidence_quality":item.get("evidence_quality","UNKNOWN"),"source_ids":item.get("source_ids",[])}
        if dimensions[name]["value"] == "UNKNOWN": unknowns.append(name)
    known=sum(x["value"] != "UNKNOWN" for x in dimensions.values())
    return {"status":"ASSESSED" if known else "UNKNOWN","dimensions":dimensions,"evidence_quality":{k:v["evidence_quality"] for k,v in dimensions.items()},"unknowns":unknowns}
