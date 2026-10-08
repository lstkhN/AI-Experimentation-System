import threading

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.api.capital as capital_api
from app.db.models import Base, CapitalAllocation, CapitalGate, CapitalPlan, Project
from app.db.session import get_db
from app.main import app
from app.engines.capital_allocator import allocate_capital
from app.engines.experiment_economics import calculate_experiment_economics
from app.schemas.capital import AllocationRequest


def test_pure_engines_are_deterministic_and_sequential():
    assert calculate_experiment_economics(estimated_cost=100, success_probability=.5, upside=300, learning_value=10)["recommended_spend"] == 100
    result = allocate_capital(150, [{"recommended_spend": 100, "gate_unlocked": True}, {"recommended_spend": 100, "gate_unlocked": True}])
    assert [item["status"] for item in result["allocations"]] == ["ALLOCATED", "PARTIAL"]


def test_equal_score_and_name_candidates_have_canonical_order_independent_of_input_order():
    candidates = [
        {"name": "same", "id": "b", "cost": 10, "probability_of_decisive_result": 1, "expected_information_gain": 1},
        {"name": "same", "id": "a", "cost": 10, "probability_of_decisive_result": 1, "expected_information_gain": 1},
    ]
    first = allocate_capital(100, [], candidate_experiments=candidates)
    second = allocate_capital(100, [], candidate_experiments=list(reversed(candidates)))
    assert [item["id"] for item in first["ranked_experiments"]] == ["a", "b"]
    assert [item["id"] for item in first["ranked_experiments"]] == [item["id"] for item in second["ranked_experiments"]]


def test_candidate_recommendations_are_deterministically_limited_to_candidate_budget():
    result = allocate_capital(100, [], candidate_experiments=[
        {"name": "second", "cost": 60, "probability_of_decisive_result": 1, "expected_information_gain": 1},
        {"name": "first", "cost": 60, "probability_of_decisive_result": 1, "expected_information_gain": 2},
        {"name": "free", "cost": 0, "probability_of_decisive_result": 1, "expected_information_gain": 1},
    ])
    assert result["candidate_budget"] == 100
    assert result["candidate_recommended_total"] == 60
    assert [item["name"] for item in result["recommended_experiments"]] == ["free", "first"]
    assert [item["candidate_status"] for item in result["ranked_experiments"]] == ["RECOMMENDED", "RECOMMENDED", "HELD_BACK"]
    assert result["do_not_commit_yet"] == 100


def test_sqlite_concurrent_allocations_reserve_budget_once(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'capital.db'}", connect_args={"check_same_thread": False, "timeout": 5})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory.begin() as db:
        project = Project(name="Concurrent capital")
        db.add(project); db.flush()
        plan = CapitalPlan(project_id=project.id, available_budget=100, recommended_spend=100)
        db.add(plan); db.flush()
        db.add(CapitalGate(capital_plan_id=plan.id, sequence=1, name="fund", recommended_spend=100, status="UNLOCKED"))
        project_id, plan_id = project.id, plan.id

    calculation_barrier = threading.Barrier(2)
    calculation_lock = threading.Lock()
    calculation_count = 0
    original_allocate_capital = capital_api.allocate_capital

    def synchronized_allocate(*args, **kwargs):
        nonlocal calculation_count
        with calculation_lock:
            calculation_count += 1
            synchronize = calculation_count <= 2
        if synchronize:
            calculation_barrier.wait(timeout=5)
        return original_allocate_capital(*args, **kwargs)

    monkeypatch.setattr(capital_api, "allocate_capital", synchronized_allocate)
    responses, errors = [], []

    def request_allocation():
        db = factory()
        try:
            responses.append(capital_api.allocate(project_id, plan_id, AllocationRequest(), db, None))
        except Exception as error:  # pragma: no cover - asserted below
            errors.append(error)
        finally:
            db.close()

    workers = [threading.Thread(target=request_allocation) for _ in range(2)]
    for worker in workers: worker.start()
    for worker in workers: worker.join()
    assert not errors
    assert sum(response["allocated_total"] for response in responses) == 100
    with factory() as db:
        assert db.scalar(select(CapitalPlan.reserved_budget).where(CapitalPlan.id == plan_id)) == 100
        assert db.scalar(select(func.sum(CapitalAllocation.allocated_spend)).where(CapitalAllocation.capital_plan_id == plan_id)) == 100
    Base.metadata.drop_all(engine); engine.dispose()


def test_allocation_idempotency_does_not_reserve_budget_twice(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'idempotency.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory.begin() as db:
        project = Project(name="Idempotent capital")
        db.add(project); db.flush()
        plan = CapitalPlan(project_id=project.id, available_budget=100, recommended_spend=100)
        db.add(plan); db.flush()
        db.add(CapitalGate(capital_plan_id=plan.id, sequence=1, name="fund", recommended_spend=100, status="UNLOCKED"))
        project_id, plan_id = project.id, plan.id
    with factory() as db:
        first = capital_api.allocate(project_id, plan_id, AllocationRequest(), db, "same-request")
    with factory() as db:
        replay = capital_api.allocate(project_id, plan_id, AllocationRequest(), db, "same-request")
    assert first["allocated_total"] == 100
    assert replay["replayed"] is True
    with factory() as db:
        assert db.scalar(select(CapitalPlan.reserved_budget).where(CapitalPlan.id == plan_id)) == 100
    Base.metadata.drop_all(engine); engine.dispose()


def test_capital_decision_allocation_alias_forwards_and_validates_idempotency_key():
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
    client = TestClient(app)
    try:
        with factory.begin() as db:
            project = Project(name="Capital decision alias")
            db.add(project)
            db.flush()
            plan = CapitalPlan(project_id=project.id, available_budget=100, recommended_spend=100)
            db.add(plan)
            db.flush()
            db.add(CapitalGate(capital_plan_id=plan.id, sequence=1, name="fund", recommended_spend=100, status="UNLOCKED"))
            project_id, plan_id = project.id, plan.id

        url = f"/api/v1/projects/{project_id}/capital/plan/{plan_id}/allocate"
        first = client.post(url, headers={"Idempotency-Key": "alias-request"}, json={})
        replay = client.post(url, headers={"Idempotency-Key": "alias-request"}, json={})
        too_long = client.post(url, headers={"Idempotency-Key": "x" * 121}, json={})

        assert first.status_code == 200
        assert first.json()["allocated_total"] == 100
        assert replay.status_code == 200
        assert replay.json()["replayed"] is True
        assert too_long.status_code == 422
        with factory() as db:
            assert db.scalar(select(CapitalPlan.reserved_budget).where(CapitalPlan.id == plan_id)) == 100
    finally:
        client.close()
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


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
        assert client.post(f"/api/v1/projects/{project['id']}/capital-plans/{plan_id}/gates/evaluate", json={"metrics": {"interviews": 10}}).json()["gates"][0]["status"] == "UNLOCKED"
        allocation = client.post(f"/api/v1/projects/{project['id']}/capital-plans/{plan_id}/allocate", json={
            "candidate_experiments": [{"name": "Fast interview", "cost": 20, "criticality": 2,
                                       "evidence_gap": 1, "probability_of_decisive_result": .8,
                                       "expected_information_gain": .9, "time_to_result_days": 1}]
        }).json()
        assert [item["status"] for item in allocation["allocations"]] == ["ALLOCATED", "PARTIAL"]
        assert allocation["ranked_experiments"][0]["name"] == "Fast interview"
    finally:
        client.close(); app.dependency_overrides.clear(); Base.metadata.drop_all(engine); engine.dispose()
