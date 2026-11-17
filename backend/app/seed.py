from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from app.auth import hash_password
from app.database import SessionLocal
from app.models import (
    Allocation,
    AllocationEvent,
    CapacityLine,
    CapacityReport,
    CapacityStorage,
    FoodBatch,
    Network,
    Site,
    SiteAssignment,
    User,
)

DEMO_PASSWORD = "pantry-demo"


def _user(session, email: str, name: str, role: str, now: datetime) -> User:
    user = User(
        email=email,
        full_name=name,
        role=role,
        password_hash=hash_password(DEMO_PASSWORD),
        created_at=now,
    )
    session.add(user)
    session.flush()
    return user


def _report(
    session,
    site: Site,
    actor: User,
    submitted_at: datetime,
    start: datetime,
    end: datetime,
    storage: list[str],
    lines: list[tuple[str, int, str]],
    unavailable: bool = False,
) -> None:
    report = CapacityReport(
        site_id=site.id,
        submitted_by=actor.id,
        submitted_at=submitted_at,
        receiving_start=start,
        receiving_end=end,
        unavailable=unavailable,
    )
    session.add(report)
    session.flush()
    for kind in storage:
        session.add(CapacityStorage(report_id=report.id, storage=kind))
    for category, quantity, unit in lines:
        session.add(
            CapacityLine(report_id=report.id, category=category, quantity=quantity, unit=unit)
        )


def seed(now: datetime | None = None) -> None:
    moment = now or datetime.now(timezone.utc)
    session = SessionLocal()
    try:
        existing = session.scalar(select(User.id).limit(1))
        if existing is not None:
            return
        _load(session, moment)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def reset(now: datetime | None = None) -> None:
    moment = now or datetime.now(timezone.utc)
    session = SessionLocal()
    try:
        for model in (
            AllocationEvent,
            Allocation,
            CapacityLine,
            CapacityStorage,
            CapacityReport,
            FoodBatch,
            SiteAssignment,
            Site,
            Network,
            User,
        ):
            session.execute(delete(model))
        _load(session, moment)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _load(session, now: datetime) -> None:
    coordinator = _user(session, "coordinator@pantrydesk.example", "Network Coordinator", "coordinator", now)
    elmwood_user = _user(session, "elmwood@pantrydesk.example", "Elmwood Steward", "steward", now)
    corktown_user = _user(session, "corktown@pantrydesk.example", "Corktown Steward", "steward", now)
    riverside_user = _user(session, "riverside@pantrydesk.example", "Riverside Steward", "steward", now)

    network = Network(name="Practice Network")
    session.add(network)
    session.flush()

    def site(name: str, address: str) -> Site:
        row = Site(
            network_id=network.id,
            name=name,
            address=address,
            area="Detroit, fictional",
            active=True,
        )
        session.add(row)
        session.flush()
        return row

    elmwood = site("Elmwood Practice Pantry", "1840 Elmwood St, Detroit")
    corktown = site("Corktown Practice Pantry", "1555 Michigan Ave, Detroit")
    lafayette = site("Lafayette Practice Pantry", "600 W Lafayette Blvd, Detroit")
    riverbend = site("Riverbend Practice Pantry", "9100 Jefferson Ave, Detroit")
    clark = site("Clark Park Practice Pantry", "1130 Clark St, Detroit")

    for user, place in (
        (elmwood_user, elmwood),
        (corktown_user, corktown),
        (riverside_user, lafayette),
        (riverside_user, riverbend),
        (riverside_user, clark),
    ):
        session.add(SiteAssignment(user_id=user.id, site_id=place.id))

    today_start = now + timedelta(hours=1)
    today_end = now + timedelta(hours=8)
    later_start = now + timedelta(days=2)
    later_end = now + timedelta(days=2, hours=4)

    _report(
        session,
        elmwood,
        elmwood_user,
        now - timedelta(hours=2),
        today_start,
        today_end,
        ["refrigerated", "ambient"],
        [("produce", 8, "crate"), ("dairy", 4, "case")],
    )
    _report(
        session,
        corktown,
        corktown_user,
        now - timedelta(hours=3),
        today_start,
        today_end,
        ["refrigerated"],
        [("produce", 6, "crate")],
    )
    _report(
        session,
        lafayette,
        riverside_user,
        now - timedelta(days=10),
        today_start,
        today_end,
        ["refrigerated"],
        [("produce", 10, "crate")],
    )
    _report(
        session,
        riverbend,
        riverside_user,
        now - timedelta(hours=1),
        today_start,
        today_end,
        ["ambient"],
        [("produce", 5, "crate")],
    )
    _report(
        session,
        clark,
        riverside_user,
        now - timedelta(hours=1),
        later_start,
        later_end,
        ["refrigerated"],
        [("produce", 5, "crate")],
    )

    earlier = now - timedelta(days=3)
    old_batch = FoodBatch(
        network_id=network.id,
        category="produce",
        quantity=5,
        unit="crate",
        storage_requirement="refrigerated",
        distribution_deadline=earlier + timedelta(hours=6),
        note="Earlier produce drop. Fictional.",
        created_by=coordinator.id,
        created_at=earlier,
    )
    session.add(old_batch)
    session.flush()
    delivered = Allocation(
        batch_id=old_batch.id,
        site_id=corktown.id,
        quantity=5,
        status="delivered",
        explanation="Seeded history so recent deliveries affect the next suggestion.",
        created_by=coordinator.id,
        created_at=earlier,
        updated_at=earlier + timedelta(hours=2),
    )
    session.add(delivered)
    session.flush()
    session.add(
        AllocationEvent(
            allocation_id=delivered.id,
            actor_id=coordinator.id,
            from_status=None,
            to_status="delivered",
            quantity=5,
            note="Recorded as already delivered.",
            created_at=earlier + timedelta(hours=2),
        )
    )

    dairy = FoodBatch(
        network_id=network.id,
        category="dairy",
        quantity=6,
        unit="case",
        storage_requirement="refrigerated",
        distribution_deadline=now + timedelta(hours=10),
        note="Dairy cases. Fictional.",
        created_by=coordinator.id,
        created_at=now - timedelta(hours=1),
    )
    produce = FoodBatch(
        network_id=network.id,
        category="produce",
        quantity=12,
        unit="crate",
        storage_requirement="refrigerated",
        distribution_deadline=now + timedelta(hours=6),
        note="Produce crates still waiting on a plan. Fictional.",
        created_by=coordinator.id,
        created_at=now,
    )
    session.add_all([dairy, produce])
    session.flush()

    canceled = Allocation(
        batch_id=dairy.id,
        site_id=elmwood.id,
        quantity=1,
        status="canceled",
        explanation="An earlier hold that was released.",
        created_by=coordinator.id,
        created_at=now - timedelta(minutes=40),
        updated_at=now - timedelta(minutes=20),
    )
    reserved = Allocation(
        batch_id=dairy.id,
        site_id=elmwood.id,
        quantity=2,
        status="reserved",
        explanation="Requested dairy, has room for 4 cases, and can receive before the evening window closes.",
        created_by=coordinator.id,
        created_at=now - timedelta(minutes=15),
        updated_at=now - timedelta(minutes=15),
    )
    session.add_all([canceled, reserved])
    session.flush()
    session.add_all(
        [
            AllocationEvent(
                allocation_id=canceled.id,
                actor_id=coordinator.id,
                from_status="reserved",
                to_status="canceled",
                quantity=1,
                note="Released the hold.",
                created_at=now - timedelta(minutes=20),
            ),
            AllocationEvent(
                allocation_id=reserved.id,
                actor_id=coordinator.id,
                from_status=None,
                to_status="reserved",
                quantity=2,
                note="Reserved from the dairy batch.",
                created_at=now - timedelta(minutes=15),
            ),
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Load fictional Pantry Desk practice data.")
    parser.add_argument("--reset", action="store_true", help="Replace existing practice data.")
    args = parser.parse_args()
    if args.reset:
        reset()
        print("Replaced the practice data.")
    else:
        seed()
        print("Practice data is ready. Demo password: pantry-demo")
        print("coordinator@pantrydesk.example")
        print("elmwood@pantrydesk.example")
        print("corktown@pantrydesk.example")
        print("riverside@pantrydesk.example")


if __name__ == "__main__":
    main()
