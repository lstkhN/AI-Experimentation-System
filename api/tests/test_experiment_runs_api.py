from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base
from app.db.session import get_db
from app.main import app


def test_local_experiment_run_lifecycle_is_deterministic_and_isolated():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)

    def override():
        db = factory()
        try: yield db
        finally: db.close()

    app.dependency_overrides[get_db] = override
    try:
        with TestClient(app) as client:
            first = client.post("/api/v1/projects", json={"name": "first"}).json()
            second = client.post("/api/v1/projects", json={"name": "second"}).json()
            base = f"/api/v1/projects/{first['id']}/experiment-runs"
            created = client.post(base, json={"title": "Demand", "forecast": {"metric": "signups", "expected_value": 10}})
            assert created.status_code == 201
            run_id = created.json()["id"]
            assert client.get(f"/api/v1/projects/{second['id']}/experiment-runs/{run_id}").status_code == 404
            assert client.post(f"{base}/{run_id}/start").status_code == 409
            assert client.post(f"{base}/{run_id}/approvals", json={"actor": "owner"}).status_code == 201
            assert client.post(f"{base}/{run_id}/start").json()["status"] == "running"
            measurement = client.post(f"{base}/{run_id}/measurements", json={"metric": "signups", "value": 12, "metadata": {"source": "manual"}})
            assert measurement.status_code == 201
            assert measurement.json()["metadata"] == {"source": "manual"}
            report = client.post(f"{base}/{run_id}/evaluate")
            assert report.status_code == 200
            assert report.json()["result"] == {"evaluation_version": "v1", "metric": "signups", "forecast_value": 10.0, "actual_value": 12.0, "delta": 2.0, "ratio": 1.2, "outcome": "met", "measurement_count": 1}
            assert client.get(f"{base}/{run_id}/actual-vs-forecast").json()["id"] == report.json()["id"]
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
