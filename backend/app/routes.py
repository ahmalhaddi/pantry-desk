from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import current_user
from app.config import settings
from app.database import get_session
from app.models import User
from app.rules import DomainError, utcnow
from app.services import (
    allocation_view,
    batch_view,
    create_batch,
    get_allocation,
    get_site,
    list_allocations,
    list_batches,
    list_sites,
    overview,
    recommend,
    reserve,
    save_draft,
    submit_report,
    _transition,
)

router = APIRouter(prefix="/api")


class BatchIn(BaseModel):
    category: str
    quantity: int
    unit: str
    storage_requirement: str
    distribution_deadline: datetime
    note: Optional[str] = None


class ReportLineIn(BaseModel):
    category: str
    quantity: int
    unit: str


class ReportIn(BaseModel):
    receiving_start: datetime
    receiving_end: datetime
    unavailable: bool = False
    storage: list[str]
    lines: list[ReportLineIn]
    note: Optional[str] = None


class SiteLineIn(BaseModel):
    site_id: int
    quantity: int


class LinesIn(BaseModel):
    lines: list[SiteLineIn]


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=utcnow().tzinfo)
    return value


def _run(session: Session, work):
    try:
        result = work()
        session.commit()
        return result
    except Exception:
        session.rollback()
        raise


def _key(value: Optional[str]) -> str:
    if value is None or not value.strip():
        raise DomainError("Idempotency-Key is required")
    return value.strip()


@router.get("/overview")
def overview_route(user: User = Depends(current_user), session: Session = Depends(get_session)):
    return overview(session, user, utcnow(), settings.capacity_fresh_hours)


@router.get("/sites")
def sites_route(
    q: Optional[str] = None,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    return list_sites(session, user, q, utcnow(), settings.capacity_fresh_hours)


@router.get("/sites/{site_id}")
def site_route(site_id: int, user: User = Depends(current_user), session: Session = Depends(get_session)):
    return get_site(session, user, site_id, utcnow(), settings.capacity_fresh_hours)


@router.post("/sites/{site_id}/reports")
def report_route(
    site_id: int,
    body: ReportIn,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    payload = body.model_dump()
    payload["receiving_start"] = _aware(body.receiving_start)
    payload["receiving_end"] = _aware(body.receiving_end)

    def work():
        report = submit_report(session, user, site_id, payload)
        return {"id": report.id, "submitted_at": report.submitted_at.isoformat()}

    return _run(session, work)


@router.get("/batches")
def batches_route(user: User = Depends(current_user), session: Session = Depends(get_session)):
    return list_batches(session, user)


@router.post("/batches")
def create_batch_route(
    body: BatchIn,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    payload = body.model_dump()
    payload["distribution_deadline"] = _aware(body.distribution_deadline)

    def work():
        return batch_view(session, create_batch(session, user, payload))

    return _run(session, work)


@router.post("/batches/{batch_id}/draft")
def draft_route(
    batch_id: int,
    body: LinesIn,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    def work():
        rows = save_draft(session, user, batch_id, [line.model_dump() for line in body.lines])
        return [allocation_view(session, row) for row in rows]

    return _run(session, work)


@router.post("/batches/{batch_id}/reserve")
def reserve_route(
    batch_id: int,
    body: LinesIn,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    key = _key(idempotency_key)

    def work():
        rows = reserve(
            session,
            user,
            batch_id,
            [line.model_dump() for line in body.lines],
            key,
            settings.capacity_fresh_hours,
        )
        return [allocation_view(session, row) for row in rows]

    return _run(session, work)


@router.get("/batches/{batch_id}/recommendations")
def recommendations_route(
    batch_id: int,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    return recommend(session, user, batch_id, settings.capacity_fresh_hours)


@router.get("/allocations")
def allocations_route(
    status: Optional[str] = None,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    return list_allocations(session, user, status)


@router.get("/allocations/{allocation_id}")
def allocation_route(
    allocation_id: int,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    return get_allocation(session, user, allocation_id)


@router.post("/allocations/{allocation_id}/deliver")
def deliver_route(
    allocation_id: int,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    key = _key(idempotency_key)

    def work():
        row = _transition(session, user, allocation_id, key, "deliver")
        return allocation_view(session, row)

    return _run(session, work)


@router.post("/allocations/{allocation_id}/cancel")
def cancel_route(
    allocation_id: int,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    key = _key(idempotency_key)

    def work():
        row = _transition(session, user, allocation_id, key, "cancel")
        return allocation_view(session, row)

    return _run(session, work)
