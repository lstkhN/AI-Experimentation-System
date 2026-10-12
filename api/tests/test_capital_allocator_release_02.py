from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base, EconomicsModel, Evidence, EvidenceSource, ExperimentRun, Hypothesis
from app.db.session import get_db
from app.main import app


def test_default_ladder_uses_plan_currency_and_persisted_blockers():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)

    def override():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override
    try:
        with TestClient(app) as client:
            project = client.post("/api/v1/projects", json={"name": "Release 0.2"}).json()
            path = f"/api/v1/projects/{project['id']}/capital-plans"
            usd = client.post(path, json={"available_budget": 2000}).json()
            eur = client.post(path, json={"available_budget": 2000, "currency": "EUR"}).json()
            assert usd["currency"] == "USD" and eur["currency"] == "EUR"
            assert [gate["recommended_spend"] for gate in usd["gates"]] == [0, 100, 500, 1000]
            assert [gate["name"].split(":")[0] for gate in usd["gates"]] == ["€0", "€100", "€500", "€1000"]

            # No reliable economics is a durable blocker and cannot be bypassed
            # by submitted metrics.
            evaluated = client.post(f"{path}/{usd['id']}/gates/evaluate", json={"metrics": {"economics_reliable": 1}}).json()
            assert all(gate["status"] == "LOCKED" for gate in evaluated["gates"])
            assert "insufficient_economics_reliability" in evaluated["gates"][0]["evaluation"]["blockers"]

            with factory() as db:
                db.add(EconomicsModel(project_id=project["id"], economics_inputs={}, result={}, reliability="RELIABLE"))
                source = EvidenceSource(project_id=project["id"], name="Contrary source")
                db.add(source); db.flush()
                db.add(Evidence(source_id=source.id, content="Demand contradicts claim", direction="contradicting", evidence_status="verified"))
                db.add(Hypothesis(project_id=project["id"], statement="fatal risk", criticality="FATAL"))
                db.add(ExperimentRun(project_id=project["id"], title="failed", status="completed", forecast={}, evaluation={"outcome": "below_forecast"}))
                db.commit()

            evaluated = client.post(f"{path}/{usd['id']}/gates/evaluate", json={"metrics": {}}).json()
            blockers = evaluated["gates"][0]["evaluation"]["blockers"]
            assert {"fatal_hypotheses", "adverse_evidence", "failed_experiments"} <= set(blockers)
            allocation = client.post(f"{path}/{usd['id']}/allocate", headers={"Idempotency-Key": "blocked"}, json={}).json()
            assert allocation["allocated_total"] == 0
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
