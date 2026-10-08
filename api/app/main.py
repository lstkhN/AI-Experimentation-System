from contextlib import asynccontextmanager
from datetime import date
import os
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from .engines.evidence import Evidence, score_evidence
from .engines.economics import UnitEconomics, unit_economics, beta_update, sample_size_proportion
from .api.projects import router as projects_router
from .api.runs import router as runs_router
from .api.hypotheses import router as hypotheses_router
from .api.evidence import router as evidence_router
from .api.verdicts import router as verdicts_router
from .api.economics import router as economics_router
from .api.experiments import router as experiments_router
from .api.experiment_runs import router as experiment_runs_router
from .api.project_verdicts import router as project_verdicts_router
from .api.strategy import router as strategy_router
from .api.capital import router as capital_router
from .api.decision import router as decision_router
from .api.candidates import router as candidates_router
from .api.capital_decision import router as capital_decision_router
from .db.session import get_db
@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Schema changes are applied by the dedicated Alembic migration job.
    yield

app = FastAPI(title="AI Business Hypothesis Analyst", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(dict.fromkeys([os.getenv("WEB_ORIGIN", "http://localhost:3000"), "http://localhost:3000", "http://127.0.0.1:3000"])),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Idempotency-Key"],
)
app.include_router(projects_router)
app.include_router(runs_router)
app.include_router(hypotheses_router)
app.include_router(evidence_router)
app.include_router(verdicts_router)
app.include_router(economics_router)
app.include_router(experiments_router)
app.include_router(experiment_runs_router)
app.include_router(project_verdicts_router)
app.include_router(strategy_router)
app.include_router(capital_router)
app.include_router(decision_router)
app.include_router(candidates_router)
app.include_router(capital_decision_router)

class EvidenceInput(BaseModel):
    tier: str = Field(pattern=r"^E[0-6]$")
    direction: str = Field(pattern="^(supporting|contradicting)$")
    relevance: float = Field(ge=0.5, le=1.0, default=1.0)
    source_quality: float = Field(ge=0.5, le=1.0, default=0.75)
    observed_on: date | None = None
    category: str = "problem"
    source_cluster: str = "unknown"
    independent: bool = True
    evidence_status: str = Field(default="verified", pattern="^(candidate|verified|rejected)$")

class EvidenceRequest(BaseModel):
    evidence: list[EvidenceInput]

class EconomicsRequest(BaseModel):
    price: float = Field(gt=0)
    variable_cost: float = Field(ge=0)
    monthly_churn: float | None = Field(default=None, gt=0, lt=1)
    cac: float | None = Field(default=None, ge=0)
    fixed_monthly_cost: float = Field(default=0, ge=0)
    target_ltv_cac_ratio: float = Field(default=3, gt=0)

class BetaRequest(BaseModel):
    alpha: float = Field(gt=0, default=1)
    beta: float = Field(gt=0, default=1)
    successes: int = Field(ge=0)
    failures: int = Field(ge=0)

@app.get("/health")
def health():
    """Liveness probe: intentionally has no dependency on external services."""
    return {"status": "ok", "version": app.version}


def _alembic_head_revision() -> str | None:
    candidates = [
        Path.cwd() / "alembic.ini",
        Path(__file__).resolve().parents[2] / "alembic.ini",
    ]
    config_path = next((path for path in candidates if path.exists()), candidates[0])
    config = Config(str(config_path))
    return ScriptDirectory.from_config(config).get_current_head()


@app.get("/ready")
@app.get("/health/ready", include_in_schema=False)
def readiness(db: Session = Depends(get_db)):
    """Readiness probe verifying a live DB connection and migration revision."""
    try:
        db.execute(text("SELECT 1"))
        revision = db.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        expected_revision = _alembic_head_revision()
    except Exception as exc:
        raise HTTPException(status_code=503, detail={"database": "unavailable", "type": type(exc).__name__}) from exc
    if revision != expected_revision:
        raise HTTPException(status_code=503, detail={"database": "ok", "revision": revision, "expected_revision": expected_revision})
    return {"status": "ok", "database": "ok", "revision": revision}

@app.post("/api/v1/evidence/score")
def evidence_score(request: EvidenceRequest):
    items = [Evidence(**item.model_dump()) for item in request.evidence]
    return score_evidence(items)

@app.post("/api/v1/economics/unit")
def economics(request: EconomicsRequest):
    return unit_economics(UnitEconomics(**request.model_dump()))

@app.post("/api/v1/economics/beta-update")
def beta(request: BetaRequest):
    return beta_update(**request.model_dump())

@app.get("/api/v1/economics/sample-size")
def sample_size(
    expected: float = Query(0.5, gt=0, lt=1),
    half_width: float = Query(0.1, gt=0),
    z: float = Query(1.96, gt=0),
):
    return {"n": sample_size_proportion(expected, half_width, z)}
