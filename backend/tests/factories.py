from __future__ import annotations

from datetime import timedelta

from app.auth import hash_password
from app.models import CapacityLine, CapacityReport, CapacityStorage, FoodBatch, Network, Site, SiteAssignment, User
from app.rules import utcnow


def make_user(session, role="coordinator", email="coordinator@example.com", name="Coordinator"):
    user = User(
        email=email,
        full_name=name,
        role=role,
        password_hash=hash_password("secret"),
        created_at=utcnow(),
    )
    session.add(user)
    session.flush()
    return user


def make_network(session):
    network = Network(name="Practice Network")
    session.add(network)
    session.flush()
    return network


def make_site(session, network, name="Elmwood Practice Pantry", steward=None):
    site = Site(
        network_id=network.id,
        name=name,
        address="100 Example St, Detroit",
        area="Detroit, fictional",
        active=True,
    )
    session.add(site)
    session.flush()
    if steward is not None:
        session.add(SiteAssignment(user_id=steward.id, site_id=site.id))
        session.flush()
    return site


def make_report(
    session,
    site,
    actor,
    now,
    category="produce",
    quantity=8,
    unit="crate",
    storage=("refrigerated",),
    hours_ago=1,
    window_start_hours=1,
    window_end_hours=8,
    unavailable=False,
):
    report = CapacityReport(
        site_id=site.id,
        submitted_by=actor.id,
        submitted_at=now - timedelta(hours=hours_ago),
        receiving_start=now + timedelta(hours=window_start_hours),
        receiving_end=now + timedelta(hours=window_end_hours),
        unavailable=unavailable,
    )
    session.add(report)
    session.flush()
    for kind in storage:
        session.add(CapacityStorage(report_id=report.id, storage=kind))
    session.add(CapacityLine(report_id=report.id, category=category, quantity=quantity, unit=unit))
    session.flush()
    return report


def make_batch(session, network, actor, now, quantity=12, category="produce", unit="crate", storage="refrigerated", deadline_hours=6):
    batch = FoodBatch(
        network_id=network.id,
        category=category,
        quantity=quantity,
        unit=unit,
        storage_requirement=storage,
        distribution_deadline=now + timedelta(hours=deadline_hours),
        note="Test batch",
        created_by=actor.id,
        created_at=now,
    )
    session.add(batch)
    session.flush()
    return batch
