from __future__ import annotations

import threading
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import AllocationEvent, CapacityReport
from app.rules import DomainError, utcnow
from app.services import _holding, _transition as change_status, recommend, reserve, submit_report
from sqlalchemy import select
from tests.factories import make_batch, make_network, make_report, make_site, make_user


def _ready(db):
    now = utcnow()
    coordinator = make_user(db)
    steward = make_user(db, role="steward", email="steward@example.com", name="Steward")
    network = make_network(db)
    site = make_site(db, network, steward=steward)
    make_report(db, site, steward, now)
    batch = make_batch(db, network, coordinator, now)
    return now, coordinator, steward, network, site, batch


def test_reserve_then_confirm_receipt(db):
    _, coordinator, steward, _, site, batch = _ready(db)
    reserved = reserve(db, coordinator, batch.id, [{"site_id": site.id, "quantity": 3}], "reserve-1", 48)
    assert reserved[0].status == "reserved"
    assert _holding(db, batch.id) == 3
    delivered = change_status(db, steward, reserved[0].id, "deliver-1", "deliver")
    assert delivered.status == "delivered"
    assert _holding(db, batch.id) == 3


def test_rejects_more_than_the_batch_has(db):
    _, coordinator, _, _, site, batch = _ready(db)
    batch.quantity = 2
    db.flush()
    with pytest.raises(DomainError, match="exceed the food batch"):
        reserve(db, coordinator, batch.id, [{"site_id": site.id, "quantity": 3}], "too-much", 48)
    assert _holding(db, batch.id) == 0


def test_rejects_more_than_the_site_can_take(db):
    _, coordinator, _, _, site, batch = _ready(db)
    with pytest.raises(DomainError, match="can take"):
        reserve(db, coordinator, batch.id, [{"site_id": site.id, "quantity": 9}], "too-full", 48)
    assert _holding(db, batch.id) == 0


def test_repeated_reserve_does_not_create_a_second_row(db):
    _, coordinator, _, _, site, batch = _ready(db)
    first = reserve(db, coordinator, batch.id, [{"site_id": site.id, "quantity": 2}], "same-key", 48)
    second = reserve(db, coordinator, batch.id, [{"site_id": site.id, "quantity": 2}], "same-key", 48)
    assert first[0].id == second[0].id
    assert _holding(db, batch.id) == 2


def test_repeated_receipt_does_not_deliver_twice(db):
    _, coordinator, steward, _, site, batch = _ready(db)
    reserved = reserve(db, coordinator, batch.id, [{"site_id": site.id, "quantity": 2}], "r", 48)
    change_status(db, steward, reserved[0].id, "same-receipt", "deliver")
    again = change_status(db, steward, reserved[0].id, "same-receipt", "deliver")
    assert again.status == "delivered"
    assert _holding(db, batch.id) == 2
    events = db.scalars(select(AllocationEvent).where(AllocationEvent.allocation_id == reserved[0].id)).all()
    assert len(events) == 2


def test_cancel_releases_the_food_once(db):
    _, coordinator, _, _, site, batch = _ready(db)
    reserved = reserve(db, coordinator, batch.id, [{"site_id": site.id, "quantity": 4}], "r", 48)
    change_status(db, coordinator, reserved[0].id, "cancel-1", "cancel")
    assert _holding(db, batch.id) == 0
    with pytest.raises(DomainError, match="no longer be canceled"):
        change_status(db, coordinator, reserved[0].id, "cancel-2", "cancel")
    assert _holding(db, batch.id) == 0


def test_cannot_deliver_a_canceled_allocation(db):
    _, coordinator, steward, _, site, batch = _ready(db)
    reserved = reserve(db, coordinator, batch.id, [{"site_id": site.id, "quantity": 1}], "r", 48)
    change_status(db, coordinator, reserved[0].id, "cancel-1", "cancel")
    with pytest.raises(DomainError, match="Only a reserved allocation"):
        change_status(db, steward, reserved[0].id, "deliver-late", "deliver")


def test_two_coordinators_cannot_take_the_last_crate(db):
    now, coordinator, steward, network, site, batch = _ready(db)
    other = make_site(db, network, name="Corktown Practice Pantry", steward=steward)
    make_report(db, other, steward, now, quantity=4)
    batch.quantity = 1
    db.flush()
    db.commit()
    batch_id = batch.id
    coordinator_id = coordinator.id
    barrier = threading.Barrier(2)
    results = []

    def attempt(site_id, key):
        local = SessionLocal()
        try:
            person = local.get(type(coordinator), coordinator_id)
            barrier.wait(timeout=5)
            reserve(local, person, batch_id, [{"site_id": site_id, "quantity": 1}], key, 48)
            local.commit()
            results.append("ok")
        except DomainError as exc:
            local.rollback()
            results.append(exc.message)
        finally:
            local.close()

    threads = [
        threading.Thread(target=attempt, args=(site.id, "left")),
        threading.Thread(target=attempt, args=(other.id, "right")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    check = SessionLocal()
    try:
        assert results.count("ok") == 1
        assert _holding(check, batch_id) == 1
    finally:
        check.close()


def test_stale_report_is_excluded_and_cannot_be_reserved(db):
    now, coordinator, steward, _, site, batch = _ready(db)
    report = db.scalar(select(CapacityReport).where(CapacityReport.site_id == site.id))
    report.submitted_at = now - timedelta(days=10)
    db.flush()
    plan = recommend(db, coordinator, batch.id, 48, now)
    assert plan["proposals"] == []
    assert "older than 48 hours" in plan["excluded"][0]["reasons"][0]
    with pytest.raises(DomainError, match="older than 48 hours"):
        reserve(db, coordinator, batch.id, [{"site_id": site.id, "quantity": 1}], "stale", 48, now)


def test_missing_storage_and_late_window_are_explained(db):
    now, coordinator, steward, network, _, batch = _ready(db)
    warm = make_site(db, network, name="Riverbend Practice Pantry", steward=steward)
    make_report(db, warm, steward, now, storage=("ambient",))
    late = make_site(db, network, name="Clark Park Practice Pantry", steward=steward)
    make_report(db, late, steward, now, window_start_hours=48, window_end_hours=52)
    plan = recommend(db, coordinator, batch.id, 48, now)
    reasons = {row["site_name"]: row["reasons"][0] for row in plan["excluded"]}
    assert "refrigerated" in reasons["Riverbend Practice Pantry"]
    assert "distribution deadline" in reasons["Clark Park Practice Pantry"]


def test_new_capacity_report_keeps_the_existing_reservation(db):
    now, coordinator, steward, network, site, batch = _ready(db)
    reserved = reserve(db, coordinator, batch.id, [{"site_id": site.id, "quantity": 4}], "hold", 48, now)
    submit_report(
        db,
        steward,
        site.id,
        {
            "receiving_start": now + timedelta(hours=1),
            "receiving_end": now + timedelta(hours=8),
            "unavailable": False,
            "storage": ["refrigerated"],
            "lines": [{"category": "produce", "quantity": 3, "unit": "crate"}],
        },
        now,
    )
    db.refresh(reserved[0])
    assert reserved[0].status == "reserved"
    assert reserved[0].quantity == 4
    later = make_batch(db, network, coordinator, now, quantity=5)
    with pytest.raises(DomainError, match="can take"):
        reserve(db, coordinator, later.id, [{"site_id": site.id, "quantity": 1}], "more", 48, now)
    assert _holding(db, batch.id) == 4


def test_steward_cannot_update_or_open_another_site(db):
    now, coordinator, steward, network, site, batch = _ready(db)
    other_steward = make_user(db, role="steward", email="other@example.com", name="Other")
    other_site = make_site(db, network, name="Other Practice Pantry", steward=other_steward)
    make_report(db, other_site, other_steward, now)
    reserved = reserve(db, coordinator, batch.id, [{"site_id": site.id, "quantity": 1}], "r", 48, now)
    db.commit()
    client = TestClient(app)
    login = client.post("/api/auth/login", json={"email": "other@example.com", "password": "secret"})
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    denied_report = client.post(
        f"/api/sites/{site.id}/reports",
        headers=headers,
        json={
            "receiving_start": (now + timedelta(hours=1)).isoformat(),
            "receiving_end": (now + timedelta(hours=4)).isoformat(),
            "storage": ["refrigerated"],
            "lines": [{"category": "produce", "quantity": 1, "unit": "crate"}],
        },
    )
    denied_delivery = client.get(f"/api/allocations/{reserved[0].id}", headers=headers)
    assert denied_report.status_code == 403
    assert denied_delivery.status_code == 403


def test_suggestion_uses_the_reported_room(db):
    now, coordinator, steward, network, site, batch = _ready(db)
    second = make_site(db, network, name="Corktown Practice Pantry", steward=steward)
    make_report(db, second, steward, now, quantity=6)
    batch.quantity = 12
    db.flush()
    plan = recommend(db, coordinator, batch.id, 48, now)
    by_name = {row["site_name"]: row for row in plan["proposals"]}
    assert by_name["Elmwood Practice Pantry"]["suggested_quantity"] == 8
    assert "8 crates" in by_name["Elmwood Practice Pantry"]["explanation"]
    assert by_name["Corktown Practice Pantry"]["suggested_quantity"] == 4
