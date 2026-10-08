from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base
from app.db.session import get_db
from app.main import app


def test_manual_strategy_records_are_crud_and_appear_in_report():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    def override():
        db = factory()
        try: yield db
        finally: db.close()
    app.dependency_overrides[get_db] = override
    client = TestClient(app)
    try:
        project_id = client.post("/api/v1/projects", json={"name": "Manual context"}).json()["id"]
        payload = {"name": "Local TAM", "entity_type": "market", "claim": "Interviewed buyers exist", "source_reference": "Interview notes 2025-03-14"}
        created = client.post(f"/api/v1/projects/{project_id}/market-entities", json=payload)
        assert created.status_code == 201
        entity_id = created.json()["id"]
        assert client.post(f"/api/v1/projects/{project_id}/competitors", json={"name": "Alternative", "competitor_type": "manual", "source_reference": "Sales call"}).status_code == 201
        assert client.put(f"/api/v1/projects/{project_id}/market-entities/{entity_id}", json={**payload, "claim": "Confirmed manually"}).json()["claim"] == "Confirmed manually"
        report = client.get(f"/api/v1/projects/{project_id}/report").json()
        assert report["market"]["status"] == "collected"
        assert report["market"]["records"][0]["provenance"] == "manual"
        assert report["competitor"]["status"] == "collected"
        assert client.delete(f"/api/v1/projects/{project_id}/market-entities/{entity_id}").status_code == 204
        assert client.post(f"/api/v1/projects/{project_id}/icp-segments", json={"name": "bad", "profile": "x", "source_reference": "x", "provenance": "llm"}).status_code == 422
    finally:
        client.close(); app.dependency_overrides.clear(); Base.metadata.drop_all(engine); engine.dispose()
