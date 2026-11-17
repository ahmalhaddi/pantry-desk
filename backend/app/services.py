from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from typing import Optional

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.models import (
    Allocation,
    AllocationEvent,
    CapacityLine,
    CapacityReport,
    CapacityStorage,
    FoodBatch,
    IdempotencyKey,
    Network,
    Site,
    SiteAssignment,
    User,
)
from app.rules import (
    ACTIVE,
    CATEGORIES,
    HOLDING,
    STORAGE,
    UNITS,
    DomainError,
    eligible_explanation,
    require_choice,
    unit_phrase,
    utcnow,
    window_problem,
)


def _network(session: Session) -> Optional[Network]:
    return session.scalar(select(Network).order_by(Network.id).limit(1))


def _assigned(session: Session, user: User, site_id: int) -> bool:
    if user.role == "coordinator":
        return True
    row = session.scalar(
        select(SiteAssignment).where(
            SiteAssignment.user_id == user.id,
            SiteAssignment.site_id == site_id,
        )
    )
    return row is not None


def _require_coordinator(user: User) -> None:
    if user.role != "coordinator":
        raise DomainError("Only a coordinator can do that", 403)


def _require_site(session: Session, user: User, site_id: int) -> Site:
    site = session.get(Site, site_id)
    if site is None:
        raise DomainError("Site not found", 404)
    if not _assigned(session, user, site.id):
        raise DomainError("You can only open your own site", 403)
    return site


def _latest_report(session: Session, site_id: int) -> Optional[CapacityReport]:
    return session.scalar(
        select(CapacityReport)
        .where(CapacityReport.site_id == site_id)
        .order_by(CapacityReport.submitted_at.desc(), CapacityReport.id.desc())
        .limit(1)
    )


def _report_storage(session: Session, report_id: int) -> list[str]:
    rows = session.scalars(select(CapacityStorage.storage).where(CapacityStorage.report_id == report_id))
    return list(rows)


def _report_lines(session: Session, report_id: int) -> list[CapacityLine]:
    return list(session.scalars(select(CapacityLine).where(CapacityLine.report_id == report_id)))


def _holding(session: Session, batch_id: int) -> int:
    value = session.scalar(
        select(func.coalesce(func.sum(Allocation.quantity), 0)).where(
            Allocation.batch_id == batch_id,
            Allocation.status.in_(HOLDING),
        )
    )
    return int(value or 0)


def reserved_against_site(
    session: Session,
    site_id: int,
    category: str,
    unit: str,
    exclude_allocation_id: Optional[int] = None,
) -> int:
    """Reserved food still occupies room on the latest capacity report.

    Delivered food is left out. A steward's new report is the room they have
    now, and subtracting deliveries again would count that food twice.
    A new report does not cancel reservations already made.
    """
    stmt = (
        select(func.coalesce(func.sum(Allocation.quantity), 0))
        .join(FoodBatch, FoodBatch.id == Allocation.batch_id)
        .where(
            Allocation.site_id == site_id,
            Allocation.status == "reserved",
            FoodBatch.category == category,
            FoodBatch.unit == unit,
        )
    )
    if exclude_allocation_id is not None:
        stmt = stmt.where(Allocation.id != exclude_allocation_id)
    return int(session.scalar(stmt) or 0)


def recent_quantity(session: Session, site_id: int, category: str, unit: str, now) -> int:
    cutoff = now - timedelta(days=14)
    value = session.scalar(
        select(func.coalesce(func.sum(Allocation.quantity), 0))
        .join(FoodBatch, FoodBatch.id == Allocation.batch_id)
        .where(
            Allocation.site_id == site_id,
            Allocation.status.in_(HOLDING),
            Allocation.created_at >= cutoff,
            FoodBatch.category == category,
            FoodBatch.unit == unit,
        )
    )
    return int(value or 0)


def inspect_site(session: Session, site: Site, batch: FoodBatch, now, fresh_hours: int) -> dict:
    reasons: list[str] = []
    info = {"need": 0, "room": 0, "recent": 0, "receiving_end": None, "reported": 0}
    if not site.active or site.network_id != batch.network_id:
        reasons.append("Site is not active.")
        return {"reasons": reasons, **info}
    report = _latest_report(session, site.id)
    if report is None:
        reasons.append("No capacity report is on file.")
        return {"reasons": reasons, **info}
    age = now - report.submitted_at
    if age > timedelta(hours=fresh_hours):
        reasons.append(f"Capacity report is older than {fresh_hours} hours.")
    if report.unavailable:
        reasons.append("Site is marked temporarily unavailable.")
    window = window_problem(report.receiving_start, report.receiving_end, batch.distribution_deadline, now)
    if window:
        reasons.append(window)
    storage = _report_storage(session, report.id)
    if batch.storage_requirement not in storage:
        reasons.append(f"Storage does not include {batch.storage_requirement}.")
    lines = _report_lines(session, report.id)
    exact = [line for line in lines if line.category == batch.category and line.unit == batch.unit]
    other_units = [line for line in lines if line.category == batch.category and line.unit != batch.unit]
    if not exact and other_units:
        reasons.append(f"Reported unit does not match this batch. This batch is tracked in {batch.unit}s.")
    elif not exact:
        reasons.append(f"No {batch.unit} quantity was reported for {batch.category.replace('_', ' ')}.")
    reported = sum(line.quantity for line in exact)
    reserved = reserved_against_site(session, site.id, batch.category, batch.unit)
    room = reported - reserved
    info.update(
        {
            "need": reported,
            "reported": reported,
            "room": max(room, 0),
            "recent": recent_quantity(session, site.id, batch.category, batch.unit, now),
            "receiving_end": report.receiving_end,
            "report_id": report.id,
        }
    )
    return {"reasons": reasons, **info}


def _event(session: Session, allocation: Allocation, actor: User, previous: Optional[str], note: str, now) -> None:
    session.add(
        AllocationEvent(
            allocation_id=allocation.id,
            actor_id=actor.id,
            from_status=previous,
            to_status=allocation.status,
            quantity=allocation.quantity,
            note=note,
            created_at=now,
        )
    )


def _replay(session: Session, actor: User, scope: str, key: str, payload_hash: str) -> Optional[list[Allocation]]:
    if not key:
        raise DomainError("Idempotency-Key is required")
    row = session.scalar(
        select(IdempotencyKey).where(
            IdempotencyKey.actor_id == actor.id,
            IdempotencyKey.scope == scope,
            IdempotencyKey.key == key,
        )
    )
    if row is None:
        return None
    if row.payload_hash != payload_hash:
        raise DomainError("This idempotency key was already used for a different request", 409)
    ids = json.loads(row.resource_ids)
    if not ids:
        return []
    return list(session.scalars(select(Allocation).where(Allocation.id.in_(ids))).all())


def _remember(session: Session, actor: User, scope: str, key: str, payload_hash: str, allocations: list[Allocation], now) -> None:
    session.add(
        IdempotencyKey(
            actor_id=actor.id,
            scope=scope,
            key=key,
            payload_hash=payload_hash,
            resource_ids=json.dumps([item.id for item in allocations]),
            created_at=now,
        )
    )


def _hash_pairs(pairs: list[tuple]) -> str:
    payload = json.dumps(pairs, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def create_batch(session: Session, actor: User, payload: dict, now=None) -> FoodBatch:
    _require_coordinator(actor)
    moment = now or utcnow()
    network = _network(session)
    if network is None:
        raise DomainError("No network has been set up", 400)
    require_choice(payload["category"], CATEGORIES, "Category")
    require_choice(payload["unit"], UNITS, "Unit")
    require_choice(payload["storage_requirement"], STORAGE, "Storage")
    quantity = int(payload["quantity"])
    if quantity < 1:
        raise DomainError("Quantity must be at least 1")
    deadline = payload["distribution_deadline"]
    if deadline <= moment:
        raise DomainError("Distribution deadline has to be in the future")
    batch = FoodBatch(
        network_id=network.id,
        category=payload["category"],
        quantity=quantity,
        unit=payload["unit"],
        storage_requirement=payload["storage_requirement"],
        distribution_deadline=deadline,
        note=payload.get("note"),
        created_by=actor.id,
        created_at=moment,
    )
    session.add(batch)
    session.flush()
    return batch


def submit_report(session: Session, actor: User, site_id: int, payload: dict, now=None) -> CapacityReport:
    moment = now or utcnow()
    site = session.scalar(select(Site).where(Site.id == site_id).with_for_update())
    if site is None:
        raise DomainError("Site not found", 404)
    if not _assigned(session, actor, site.id):
        raise DomainError("You can only update your own site", 403)
    start = payload["receiving_start"]
    end = payload["receiving_end"]
    if end <= start:
        raise DomainError("Receiving window is not a real time range")
    storage = payload["storage"]
    if not storage:
        raise DomainError("Choose at least one storage type")
    for kind in storage:
        require_choice(kind, STORAGE, "Storage")
    report = CapacityReport(
        site_id=site.id,
        submitted_by=actor.id,
        submitted_at=moment,
        receiving_start=start,
        receiving_end=end,
        unavailable=bool(payload.get("unavailable", False)),
        note=payload.get("note"),
    )
    session.add(report)
    session.flush()
    for kind in dict.fromkeys(storage):
        session.add(CapacityStorage(report_id=report.id, storage=kind))
    for line in payload["lines"]:
        require_choice(line["category"], CATEGORIES, "Category")
        require_choice(line["unit"], UNITS, "Unit")
        quantity = int(line["quantity"])
        if quantity < 0:
            raise DomainError("Quantity cannot be negative")
        session.add(
            CapacityLine(
                report_id=report.id,
                category=line["category"],
                quantity=quantity,
                unit=line["unit"],
            )
        )
    session.flush()
    return report


def batch_view(session: Session, batch: FoodBatch) -> dict:
    remaining = batch.quantity - _holding(session, batch.id)
    return {
        "id": batch.id,
        "category": batch.category,
        "quantity": batch.quantity,
        "remaining_quantity": remaining,
        "unit": batch.unit,
        "storage_requirement": batch.storage_requirement,
        "distribution_deadline": batch.distribution_deadline.isoformat(),
        "note": batch.note,
    }


def list_batches(session: Session, actor: User) -> list[dict]:
    if actor.role not in ("coordinator", "steward"):
        raise DomainError("Sign in required", 401)
    rows = session.scalars(select(FoodBatch).order_by(FoodBatch.distribution_deadline, FoodBatch.id)).all()
    return [batch_view(session, batch) for batch in rows]


def site_summary(session: Session, site: Site, now, fresh_hours: int) -> dict:
    report = _latest_report(session, site.id)
    fresh = False
    needs = []
    storage: list[str] = []
    unavailable = False
    last_at = None
    receiving_start = None
    receiving_end = None
    if report is not None:
        last_at = report.submitted_at.isoformat()
        fresh = (now - report.submitted_at) <= timedelta(hours=fresh_hours)
        unavailable = report.unavailable
        receiving_start = report.receiving_start.isoformat()
        receiving_end = report.receiving_end.isoformat()
        storage = _report_storage(session, report.id)
        needs = [
            {"category": line.category, "quantity": line.quantity, "unit": line.unit}
            for line in _report_lines(session, report.id)
        ]
    return {
        "id": site.id,
        "name": site.name,
        "address": site.address,
        "area": site.area,
        "active": site.active,
        "last_submitted_at": last_at,
        "fresh": fresh,
        "unavailable": unavailable,
        "receiving_start": receiving_start,
        "receiving_end": receiving_end,
        "storage": storage,
        "needs": needs,
        "synthetic": True,
    }


def list_sites(session: Session, actor: User, query: Optional[str], now, fresh_hours: int) -> list[dict]:
    stmt = select(Site).order_by(Site.name)
    if actor.role == "steward":
        stmt = (
            select(Site)
            .join(SiteAssignment, SiteAssignment.site_id == Site.id)
            .where(SiteAssignment.user_id == actor.id)
            .order_by(Site.name)
        )
    elif actor.role != "coordinator":
        raise DomainError("Sign in required", 401)
    if query:
        like = f"%{query.strip()}%"
        stmt = stmt.where(or_(Site.name.ilike(like), Site.address.ilike(like), Site.area.ilike(like)))
    return [site_summary(session, site, now, fresh_hours) for site in session.scalars(stmt).all()]


def get_site(session: Session, actor: User, site_id: int, now, fresh_hours: int) -> dict:
    site = _require_site(session, actor, site_id)
    return site_summary(session, site, now, fresh_hours)


def allocation_view(session: Session, allocation: Allocation) -> dict:
    batch = session.get(FoodBatch, allocation.batch_id)
    site = session.get(Site, allocation.site_id)
    events = session.scalars(
        select(AllocationEvent)
        .where(AllocationEvent.allocation_id == allocation.id)
        .order_by(AllocationEvent.created_at, AllocationEvent.id)
    ).all()
    warning = None
    if allocation.status == "reserved" and batch is not None:
        report = _latest_report(session, allocation.site_id)
        reported = 0
        if report is not None:
            reported = sum(
                line.quantity
                for line in _report_lines(session, report.id)
                if line.category == batch.category and line.unit == batch.unit
            )
        held = reserved_against_site(session, allocation.site_id, batch.category, batch.unit)
        if reported < held:
            warning = "A newer capacity report lists less room than this reservation. The reservation is still held."
    return {
        "id": allocation.id,
        "batch_id": allocation.batch_id,
        "site_id": allocation.site_id,
        "site_name": site.name if site else "",
        "category": batch.category if batch else "",
        "unit": batch.unit if batch else "",
        "quantity": allocation.quantity,
        "quantity_label": unit_phrase(allocation.quantity, batch.unit) if batch else str(allocation.quantity),
        "status": allocation.status,
        "explanation": allocation.explanation,
        "warning": warning,
        "receiving_deadline": batch.distribution_deadline.isoformat() if batch else None,
        "events": [
            {
                "from_status": event.from_status,
                "to_status": event.to_status,
                "quantity": event.quantity,
                "note": event.note,
                "created_at": event.created_at.isoformat(),
            }
            for event in events
        ],
    }


def _require_allocation_view(session: Session, actor: User, allocation: Allocation) -> None:
    if not _assigned(session, actor, allocation.site_id):
        raise DomainError("You can only open deliveries for your own site", 403)


def get_allocation(session: Session, actor: User, allocation_id: int) -> dict:
    allocation = session.get(Allocation, allocation_id)
    if allocation is None:
        raise DomainError("Allocation not found", 404)
    _require_allocation_view(session, actor, allocation)
    return allocation_view(session, allocation)


def list_allocations(session: Session, actor: User, status: Optional[str]) -> list[dict]:
    stmt = select(Allocation).order_by(Allocation.created_at.desc(), Allocation.id.desc())
    if actor.role == "steward":
        stmt = (
            select(Allocation)
            .join(SiteAssignment, SiteAssignment.site_id == Allocation.site_id)
            .where(SiteAssignment.user_id == actor.id)
            .order_by(Allocation.created_at.desc(), Allocation.id.desc())
        )
    elif actor.role != "coordinator":
        raise DomainError("Sign in required", 401)
    if status:
        stmt = stmt.where(Allocation.status == status)
    return [allocation_view(session, row) for row in session.scalars(stmt).all()]


def reserve(
    session: Session,
    actor: User,
    batch_id: int,
    lines: list[dict],
    idempotency_key: str,
    fresh_hours: int,
    now=None,
) -> list[Allocation]:
    _require_coordinator(actor)
    moment = now or utcnow()
    if not lines:
        raise DomainError("Choose at least one site")
    pairs = [(int(line["site_id"]), int(line["quantity"])) for line in lines]
    if any(quantity < 1 for _, quantity in pairs):
        raise DomainError("Quantity must be at least 1")
    payload_hash = _hash_pairs(pairs)
    scope = f"reserve:{batch_id}"
    replay = _replay(session, actor, scope, idempotency_key, payload_hash)
    if replay is not None:
        return replay

    batch = session.scalar(select(FoodBatch).where(FoodBatch.id == batch_id).with_for_update())
    if batch is None:
        raise DomainError("Food batch not found", 404)
    sites: dict[int, Site] = {}
    for site_id in sorted({site_id for site_id, _ in pairs}):
        site = session.scalar(select(Site).where(Site.id == site_id).with_for_update())
        if site is None:
            raise DomainError("Site not found", 404)
        sites[site_id] = site

    requested = sum(quantity for _, quantity in pairs)
    remaining = batch.quantity - _holding(session, batch.id)
    if requested > remaining:
        raise DomainError("Reserved and delivered quantities would exceed the food batch", 409)

    created: list[Allocation] = []
    for site_id, quantity in pairs:
        site = sites[site_id]
        look = inspect_site(session, site, batch, moment, fresh_hours)
        if look["reasons"]:
            raise DomainError(f"{site.name}: {look['reasons'][0]}", 409)
        already = session.scalar(
            select(Allocation).where(
                Allocation.batch_id == batch.id,
                Allocation.site_id == site.id,
                Allocation.status.in_(ACTIVE),
            )
        )
        reserved_now = reserved_against_site(
            session,
            site.id,
            batch.category,
            batch.unit,
            exclude_allocation_id=already.id if already is not None else None,
        )
        room = look["reported"] - reserved_now
        if quantity > room:
            raise DomainError(
                f"{site.name} can take {unit_phrase(max(room, 0), batch.unit)}, not {unit_phrase(quantity, batch.unit)}",
                409,
            )
        explanation = eligible_explanation(batch.category, batch.unit, room, look["receiving_end"])
        if already is not None and already.status == "reserved":
            raise DomainError(f"{site.name} already has a reservation for this batch", 409)
        if already is not None and already.status == "draft":
            previous = already.status
            already.quantity = quantity
            already.status = "reserved"
            already.explanation = explanation
            already.updated_at = moment
            session.flush()
            _event(session, already, actor, previous, "Reserved the draft.", moment)
            created.append(already)
            continue
        allocation = Allocation(
            batch_id=batch.id,
            site_id=site.id,
            quantity=quantity,
            status="reserved",
            explanation=explanation,
            created_by=actor.id,
            created_at=moment,
            updated_at=moment,
        )
        session.add(allocation)
        session.flush()
        _event(session, allocation, actor, None, "Reserved food for the site.", moment)
        created.append(allocation)

    _remember(session, actor, scope, idempotency_key, payload_hash, created, moment)
    session.flush()
    return created


def _transition(
    session: Session,
    actor: User,
    allocation_id: int,
    idempotency_key: str,
    action: str,
    now=None,
) -> Allocation:
    moment = now or utcnow()
    scope = f"{action}:{allocation_id}"
    payload_hash = _hash_pairs([(action, allocation_id)])
    replay = _replay(session, actor, scope, idempotency_key, payload_hash)
    if replay is not None:
        return replay[0]

    peek = session.get(Allocation, allocation_id)
    if peek is None:
        raise DomainError("Allocation not found", 404)
    batch = session.scalar(select(FoodBatch).where(FoodBatch.id == peek.batch_id).with_for_update())
    if batch is None:
        raise DomainError("Food batch not found", 404)
    session.scalar(select(Site).where(Site.id == peek.site_id).with_for_update())
    allocation = session.scalar(select(Allocation).where(Allocation.id == allocation_id).with_for_update())
    if allocation is None:
        raise DomainError("Allocation not found", 404)

    if action == "cancel":
        _require_coordinator(actor)
        if allocation.status not in ("draft", "reserved"):
            raise DomainError("This allocation can no longer be canceled", 409)
        note = "Canceled the reservation and released the food."
    else:
        if not _assigned(session, actor, allocation.site_id):
            raise DomainError("You can only confirm a delivery for your own site", 403)
        if allocation.status != "reserved":
            raise DomainError("Only a reserved allocation can be marked delivered", 409)
        note = "Confirmed the site received the food."

    previous = allocation.status
    allocation.status = "canceled" if action == "cancel" else "delivered"
    allocation.updated_at = moment
    session.flush()
    _event(session, allocation, actor, previous, note, moment)
    _remember(session, actor, scope, idempotency_key, payload_hash, [allocation], moment)
    session.flush()
    return allocation


def overview(session: Session, actor: User, now, fresh_hours: int) -> dict:
    sites = list_sites(session, actor, None, now, fresh_hours)
    needing = []
    for site in sites:
        if site["last_submitted_at"] is None:
            needing.append({"id": site["id"], "name": site["name"], "reason": "No capacity report is on file."})
        elif not site["fresh"]:
            needing.append({"id": site["id"], "name": site["name"], "reason": "Capacity report is out of date."})
    batches = list_batches(session, actor)
    pending = list_allocations(session, actor, "reserved")
    next_action = {"label": "Record available food", "href": "/batches"}
    open_batch = next((batch for batch in batches if batch["remaining_quantity"] > 0), None)
    if open_batch is not None and actor.role == "coordinator":
        next_action = {
            "label": f"Review {open_batch['category'].replace('_', ' ')} still available",
            "href": f"/batches/{open_batch['id']}",
        }
    elif needing:
        next_action = {"label": "Ask a site for a fresh capacity report", "href": "/sites"}
    elif pending and actor.role == "steward":
        next_action = {"label": "Confirm a delivery", "href": f"/allocations/{pending[0]['id']}"}
    return {
        "next_action": next_action,
        "batches": [batch for batch in batches if batch["remaining_quantity"] > 0],
        "pending": pending,
        "sites_needing_updates": needing,
        "synthetic": True,
    }


def save_draft(session: Session, actor: User, batch_id: int, lines: list[dict], now=None) -> list[Allocation]:
    _require_coordinator(actor)
    moment = now or utcnow()
    batch = session.scalar(select(FoodBatch).where(FoodBatch.id == batch_id).with_for_update())
    if batch is None:
        raise DomainError("Food batch not found", 404)
    total = 0
    parsed: list[tuple[int, int]] = []
    for line in lines:
        quantity = int(line["quantity"])
        if quantity < 1:
            raise DomainError("Quantity must be at least 1")
        total += quantity
        parsed.append((int(line["site_id"]), quantity))
    if total > batch.quantity - _holding(session, batch.id):
        raise DomainError("The draft asks for more food than the batch has left", 409)
    draft_ids = list(
        session.scalars(
            select(Allocation.id).where(Allocation.batch_id == batch.id, Allocation.status == "draft")
        ).all()
    )
    if draft_ids:
        session.execute(delete(AllocationEvent).where(AllocationEvent.allocation_id.in_(draft_ids)))
        session.execute(delete(Allocation).where(Allocation.id.in_(draft_ids)))
    created = []
    for site_id, quantity in parsed:
        site = session.get(Site, site_id)
        if site is None:
            raise DomainError("Site not found", 404)
        existing = session.scalar(
            select(Allocation).where(
                Allocation.batch_id == batch.id,
                Allocation.site_id == site.id,
                Allocation.status == "reserved",
            )
        )
        if existing is not None:
            raise DomainError(f"{site.name} already has a reservation for this batch", 409)
        allocation = Allocation(
            batch_id=batch.id,
            site_id=site.id,
            quantity=quantity,
            status="draft",
            explanation=None,
            created_by=actor.id,
            created_at=moment,
            updated_at=moment,
        )
        session.add(allocation)
        session.flush()
        _event(session, allocation, actor, None, "Saved a draft proposal.", moment)
        created.append(allocation)
    session.flush()
    return created


def recommend(session: Session, actor: User, batch_id: int, fresh_hours: int, now=None) -> dict:
    _require_coordinator(actor)
    moment = now or utcnow()
    batch = session.get(FoodBatch, batch_id)
    if batch is None:
        raise DomainError("Food batch not found", 404)
    sites = session.scalars(select(Site).where(Site.network_id == batch.network_id).order_by(Site.name)).all()
    proposals = []
    excluded = []
    for site in sites:
        look = inspect_site(session, site, batch, moment, fresh_hours)
        if look["reasons"]:
            excluded.append({"site_id": site.id, "site_name": site.name, "reasons": look["reasons"]})
            continue
        proposals.append(
            {
                "site_id": site.id,
                "site_name": site.name,
                "need": look["need"],
                "room": look["room"],
                "recent": look["recent"],
                "score": look["need"] - look["recent"],
                "receiving_end": look["receiving_end"],
            }
        )
    proposals.sort(key=lambda item: (-item["score"], item["site_name"]))
    remaining = batch.quantity - _holding(session, batch.id)
    left = remaining
    ranked = []
    for item in proposals:
        take = min(item["need"], item["room"], left)
        take = max(take, 0)
        left -= take
        text = eligible_explanation(batch.category, batch.unit, item["room"], item["receiving_end"])
        if item["recent"]:
            text += f" {unit_phrase(item['recent'], batch.unit)} were reserved or delivered in the last 14 days."
        if take == 0 and remaining == 0:
            text += " This batch has no quantity left to reserve."
        elif take == 0 and item["room"] > 0:
            text += " Higher ranked sites already use the remaining quantity."
        ranked.append(
            {
                "site_id": item["site_id"],
                "site_name": item["site_name"],
                "suggested_quantity": take,
                "explanation": text,
                "need": item["need"],
                "room": item["room"],
                "recent": item["recent"],
            }
        )
    return {"batch": batch_view(session, batch), "proposals": ranked, "excluded": excluded}
