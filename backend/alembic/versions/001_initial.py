"""sites, batches, and allocations

Revision ID: 001_initial
Revises:
Create Date: 2026-11-16

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("full_name", sa.String(200), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "networks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
    )
    op.create_table(
        "sites",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("network_id", sa.Integer(), sa.ForeignKey("networks.id"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("address", sa.String(300), nullable=False),
        sa.Column("area", sa.String(120), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "site_assignments",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("site_id", sa.Integer(), sa.ForeignKey("sites.id"), primary_key=True),
    )
    op.create_table(
        "capacity_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("site_id", sa.Integer(), sa.ForeignKey("sites.id"), nullable=False),
        sa.Column("submitted_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("receiving_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("receiving_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("unavailable", sa.Boolean(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
    )
    op.create_index("ix_capacity_reports_site_id", "capacity_reports", ["site_id"])
    op.create_table(
        "capacity_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("report_id", sa.Integer(), sa.ForeignKey("capacity_reports.id"), nullable=False),
        sa.Column("category", sa.String(40), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit", sa.String(20), nullable=False),
        sa.CheckConstraint("quantity >= 0", name="ck_capacity_line_qty"),
    )
    op.create_index("ix_capacity_lines_report_id", "capacity_lines", ["report_id"])
    op.create_table(
        "capacity_storage",
        sa.Column("report_id", sa.Integer(), sa.ForeignKey("capacity_reports.id"), primary_key=True),
        sa.Column("storage", sa.String(32), primary_key=True),
    )
    op.create_table(
        "food_batches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("network_id", sa.Integer(), sa.ForeignKey("networks.id"), nullable=False),
        sa.Column("category", sa.String(40), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit", sa.String(20), nullable=False),
        sa.Column("storage_requirement", sa.String(32), nullable=False),
        sa.Column("distribution_deadline", sa.DateTime(timezone=True), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_batch_qty"),
    )
    op.create_table(
        "allocations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batch_id", sa.Integer(), sa.ForeignKey("food_batches.id"), nullable=False),
        sa.Column("site_id", sa.Integer(), sa.ForeignKey("sites.id"), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_allocation_qty"),
        sa.CheckConstraint(
            "status IN ('draft', 'reserved', 'delivered', 'canceled')",
            name="ck_allocation_status",
        ),
    )
    op.create_index("ix_allocations_batch_id", "allocations", ["batch_id"])
    op.create_index("ix_allocations_site_id", "allocations", ["site_id"])
    op.create_index(
        "uq_active_allocation",
        "allocations",
        ["batch_id", "site_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('draft', 'reserved')"),
    )
    op.create_table(
        "allocation_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("allocation_id", sa.Integer(), sa.ForeignKey("allocations.id"), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("from_status", sa.String(20), nullable=True),
        sa.Column("to_status", sa.String(20), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_allocation_events_allocation_id", "allocation_events", ["allocation_id"])


def downgrade() -> None:
    op.drop_table("allocation_events")
    op.drop_table("allocations")
    op.drop_table("food_batches")
    op.drop_table("capacity_storage")
    op.drop_table("capacity_lines")
    op.drop_table("capacity_reports")
    op.drop_table("site_assignments")
    op.drop_table("sites")
    op.drop_table("networks")
    op.drop_table("users")
