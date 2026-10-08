import threading

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base
from app.db.session import get_db
from app.main import app
from app.engines.capital_allocator import allocate_capital
from app.engines.experiment_economics import calculate_experiment_economics


def test_pure_engines_are_deterministic_and_sequential():
    assert calculate_experiment_economics(estimated_cost=100, success_probability=.5, upside=300, learning_value=10)["recommended_spend"] == 100
    result = allocate_capital(150, [{"recommended_spend": 100, "gate_unlocked": True}, {"recommended_spend": 100, "gate_unlocked": True}])
    assert [item["status"] for item in result["allocations"]] == ["ALLOCATED", "PARTIAL"]


def test_capital_plan_gate_evaluation_and_allocation():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine); factory = sessionmaker(bind=engine)
    def override():
        db = factory()
        try: yield db
        finally: db.close()
    app.dependency_overrides[get_db] = override
    client = TestClient(app)
    try:
        project = client.post("/api/v1/projects", json={"name": "Capital"}).json()
        response = client.post(f"/api/v1/projects/{project['id']}/capital-plans", json={"available_budget": 150, "gates": [
            {"name": "learn", "recommended_spend": 100, "unlock_conditions": [{"metric": "interviews", "operator": ">=", "value": 10}]},
            {"name": "scale", "recommended_spend": 100},
        ]})
        assert response.status_code == 200
        plan_id = response.json()["id"]
        assert client.get(f"/api/v1/projects/{project['id']}/capital-plans").json()[0]["id"] == plan_id
        replay = client.post(f"/api/v1/projects/{project['id']}/capital-plans", headers={"Idempotency-Key": "create-once"}, json={"available_budget": 10, "gates": []})
        assert replay.status_code == 200
        assert client.post(f"/api/v1/projects/{project['id']}/capital-plans", headers={"Idempotency-Key": "create-once"}, json={"available_budget": 10, "gates": []}).json()["id"] == replay.json()["id"]
        assert client.post(f"/api/v1/projects/{project['id']}/capital-plans/{plan_id}/gates/evaluate", json={"metrics": {"interviews": 10}}).json()["gates"][0]["status"] == "UNLOCKED"
        allocation = client.post(f"/api/v1/projects/{project['id']}/capital-plans/{plan_id}/allocate", headers={"Idempotency-Key": "allocation-intent"}, json={}).json()
        assert [item["status"] for item in allocation["allocations"]] == ["ALLOCATED", "PARTIAL"]
        assert client.post(f"/api/v1/projects/{project['id']}/capital-plans/{plan_id}/allocate", headers={"Idempotency-Key": "allocation-intent"}, json={}).json()["replayed"] is True
        persisted = next(item for item in client.get(f"/api/v1/projects/{project['id']}/capital-plans").json() if item["id"] == plan_id)
        assert [item["status"] for item in persisted["allocations"]] == ["ALLOCATED", "PARTIAL"]
        # A fresh intent sees each gate's remaining commitment, not its full
        # recommendation, and therefore cannot fund completed gates again.
        second = client.post(f"/api/v1/projects/{project['id']}/capital-plans/{plan_id}/allocate", headers={"Idempotency-Key": "allocation-second"}, json={}).json()
        assert [item["requested_spend"] for item in second["allocations"]] == [0, 50]
        assert sum(item["allocated_spend"] for item in second["allocations"]) == 0
        persisted = next(item for item in client.get(f"/api/v1/projects/{project['id']}/capital-plans").json() if item["id"] == plan_id)
        assert sum(item["allocated_spend"] for item in persisted["allocations"]) == 150
    finally:
        client.close(); app.dependency_overrides.clear(); Base.metadata.drop_all(engine); engine.dispose()


def test_capital_decision_alias_forwards_idempotency_key():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine); factory = sessionmaker(bind=engine)
    def override():
        db = factory()
        try: yield db
        finally: db.close()
    app.dependency_overrides[get_db] = override
    try:
        with TestClient(app) as client:
            project = client.post("/api/v1/projects", json={"name": "Capital alias"}).json()
            path = f"/api/v1/projects/{project['id']}/capital/plan"
            first = client.post(path, headers={"Idempotency-Key": "alias-plan"}, json={"available_budget": 20, "gates": []})
            second = client.post(path, headers={"Idempotency-Key": "alias-plan"}, json={"available_budget": 20, "gates": []})
            assert first.status_code == second.status_code == 200
            assert first.json()["id"] == second.json()["id"]
    finally:
        app.dependency_overrides.clear(); Base.metadata.drop_all(engine); engine.dispose()


def _sqlite_concurrent_requests(factory, request):
    barrier = threading.Barrier(2)

    def wait_for_racing_flush(session, _flush_context, _instances):
        if threading.current_thread().name.startswith("capital-race") and not session.info.get("racing_flush"):
            session.info["racing_flush"] = True
            barrier.wait(timeout=10)

    event.listen(factory.class_, "before_flush", wait_for_racing_flush)
    responses = []
    errors = []

    def run_request():
        try:
            with TestClient(app) as client:
                responses.append(request(client))
        except Exception as error:  # pragma: no cover - assertion below reports failures
            errors.append(error)

    try:
        threads = [threading.Thread(target=run_request, name=f"capital-race-{index}") for index in range(2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(timeout=15)
        assert not any(thread.is_alive() for thread in threads)
        assert not errors
        return responses
    finally:
        event.remove(factory.class_, "before_flush", wait_for_racing_flush)


def test_sqlite_concurrent_capital_plan_creation_reloads_idempotent_plan(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'capital.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine); factory = sessionmaker(bind=engine)

    def override():
        db = factory()
        try: yield db
        finally: db.close()

    app.dependency_overrides[get_db] = override
    try:
        with TestClient(app) as client:
            project = client.post("/api/v1/projects", json={"name": "Concurrent capital"}).json()
        responses = _sqlite_concurrent_requests(factory, lambda client: client.post(
            f"/api/v1/projects/{project['id']}/capital-plans", headers={"Idempotency-Key": "same-plan"},
            json={"available_budget": 100, "gates": []},
        ))
        assert [response.status_code for response in responses] == [200, 200]
        assert len({response.json()["id"] for response in responses}) == 1
        with TestClient(app) as client:
            assert len(client.get(f"/api/v1/projects/{project['id']}/capital-plans").json()) == 1
    finally:
        app.dependency_overrides.clear(); Base.metadata.drop_all(engine); engine.dispose()


def test_sqlite_concurrent_distinct_allocation_keys_preserve_budget_invariant(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'distinct-allocation.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine); factory = sessionmaker(bind=engine)
    def override():
        db = factory()
        try: yield db
        finally: db.close()
    app.dependency_overrides[get_db] = override
    try:
        with TestClient(app) as client:
            project = client.post("/api/v1/projects", json={"name": "Distinct allocation"}).json()
            plan = client.post(f"/api/v1/projects/{project['id']}/capital-plans", json={"available_budget": 100, "gates": [{"name": "fund", "recommended_spend": 100, "unlock_conditions": []}]}).json()
            client.post(f"/api/v1/projects/{project['id']}/capital-plans/{plan['id']}/gates/evaluate", json={"metrics": {}})
        responses = _sqlite_concurrent_requests(factory, lambda client: client.post(
            f"/api/v1/projects/{project['id']}/capital-plans/{plan['id']}/allocate",
            headers={"Idempotency-Key": threading.current_thread().name}, json={},
        ))
        assert [response.status_code for response in responses] == [200, 200]
        with TestClient(app) as client:
            persisted = client.get(f"/api/v1/projects/{project['id']}/capital-plans").json()[0]
        allocated = [item["allocated_spend"] for item in persisted["allocations"]]
        assert sum(allocated) <= 100
        assert all(item >= 0 for item in allocated)
    finally:
        app.dependency_overrides.clear(); Base.metadata.drop_all(engine); engine.dispose()


def test_sqlite_concurrent_same_key_allocation_replays_without_overspending(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'allocation.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine); factory = sessionmaker(bind=engine)

    def override():
        db = factory()
        try: yield db
        finally: db.close()

    app.dependency_overrides[get_db] = override
    try:
        with TestClient(app) as client:
            project = client.post("/api/v1/projects", json={"name": "Concurrent allocation"}).json()
            plan = client.post(f"/api/v1/projects/{project['id']}/capital-plans", json={"available_budget": 100, "gates": [
                {"name": "fund", "recommended_spend": 100, "unlock_conditions": []},
            ]}).json()
            client.post(f"/api/v1/projects/{project['id']}/capital-plans/{plan['id']}/gates/evaluate", json={"metrics": {}})
        responses = _sqlite_concurrent_requests(factory, lambda client: client.post(
            f"/api/v1/projects/{project['id']}/capital-plans/{plan['id']}/allocate",
            headers={"Idempotency-Key": "same-allocation"}, json={},
        ))
        assert [response.status_code for response in responses] == [200, 200]
        assert sum(response.json().get("replayed", False) for response in responses) == 1
        with TestClient(app) as client:
            persisted = client.get(f"/api/v1/projects/{project['id']}/capital-plans").json()[0]
        assert len(persisted["allocations"]) == 1
        assert sum(item["allocated_spend"] for item in persisted["allocations"]) <= 100
    finally:
        app.dependency_overrides.clear(); Base.metadata.drop_all(engine); engine.dispose()
