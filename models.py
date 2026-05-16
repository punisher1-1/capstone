"""
models.py — SQLAlchemy ORM models for MakerSpaceHub.

Each class here maps to one database table. SQLAlchemy uses these
classes to generate SQL for queries and to materialize query results
back into typed Python objects.

Currently defines: Equipment, Member, Reservation, CheckIn.
"""
from datetime import date, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class Equipment(Base):
    """A piece of equipment available in the makerspace."""
    __tablename__ = "equipment"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100))
    category: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20), default="available")
    location: Mapped[Optional[str]] = mapped_column(String(100))

    def __repr__(self) -> str:
        return f"<Equipment id={self.id} name={self.name!r} status={self.status}>"


class Member(Base):
    """A member of the makerspace (student, staff, community, or faculty)."""
    __tablename__ = "member"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    first_name: Mapped[str] = mapped_column(String(50))
    last_name: Mapped[str] = mapped_column(String(50))
    email: Mapped[str] = mapped_column(String(100), unique=True)
    phone: Mapped[Optional[str]] = mapped_column(String(20))
    membership_type: Mapped[str] = mapped_column(String(20), default="student")
    join_date: Mapped[date] = mapped_column(Date, default=date.today)
    is_active: Mapped[bool] = mapped_column(default=True)

    def __repr__(self) -> str:
        return f"<Member id={self.id} email={self.email!r} active={self.is_active}>"


class Reservation(Base):
    """A reservation of equipment by a member for a specific time window."""
    __tablename__ = "reservation"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("member.id"))
    equipment_id: Mapped[int] = mapped_column(ForeignKey("equipment.id"))
    start_time: Mapped[datetime] = mapped_column(DateTime)
    end_time: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(20), default="confirmed")
    notes: Mapped[Optional[str]] = mapped_column(Text)

    member: Mapped["Member"] = relationship()
    equipment: Mapped["Equipment"] = relationship()

    @property
    def member_name(self) -> str:
        return f"{self.member.first_name} {self.member.last_name}"

    @property
    def equipment_name(self) -> str:
        return self.equipment.name

    def __repr__(self) -> str:
        return (f"<Reservation id={self.id} member={self.member_id} "
                f"equipment={self.equipment_id} status={self.status}>")


class CheckIn(Base):
    """
    A check-in record showing when a member entered (and optionally exited)
    the makerspace. May reference a Reservation if the member is here for
    a scheduled equipment session, or stand alone for open studio time.
    """
    __tablename__ = "checkin"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("member.id"))

    # server_default=func.now() lets PostgreSQL fill in CURRENT_TIMESTAMP
    # at insert time. More accurate than a Python-side default — the value
    # reflects when the database actually recorded the row, not when the
    # Python process prepared it.
    check_in_time: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )

    # NULL until the member checks out. The presence/absence of this value
    # is what 'active=1' filters on in the list endpoint.
    check_out_time: Mapped[Optional[datetime]] = mapped_column(DateTime)

    purpose: Mapped[Optional[str]] = mapped_column(String(100))

    # Optional FK — a check-in doesn't require a reservation.
    reservation_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("reservation.id")
    )

    member: Mapped["Member"] = relationship()
    reservation: Mapped[Optional["Reservation"]] = relationship()

    @property
    def member_name(self) -> str:
        return f"{self.member.first_name} {self.member.last_name}"

    @property
    def equipment_name(self) -> Optional[str]:
        """Equipment name from the linked reservation, if any."""
        if self.reservation is None:
            return None
        return self.reservation.equipment.name

    def __repr__(self) -> str:
        return (f"<CheckIn id={self.id} member={self.member_id} "
                f"checked_out={self.check_out_time is not None}>")
"""
Consumable ORM model entered into models.py alongside Member, Equipment, etc.

Why SQLAlchemy 2.0 mapped_column style:
  - Matches the existing models.py pattern.
  - Gives static type information (Mapped[int]) so editors and mypy can
    catch silly mistakes like assigning a str to an int column.
  - Cleaner than the legacy Column(...) attribute style.

Why we keep the column name `consumable_id` (instead of plain `id`):
  - The Unit 4 ERD and CRUD plan reference `consumable_id` by name.
  - SRS traceability is easier when the column name matches the design doc.
  - Note: this departs slightly from the other 4 tables, which use `id`.
    The Python attribute is still called `consumable_id` here for clarity,
    but you can map it as `id: Mapped[int] = mapped_column("consumable_id", ...)`
    if you want internal consistency. Pick one and update the wiki entity page.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import String, Numeric, DateTime, CheckConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base  # adjust import to match your project (app.database, etc.)


class Consumable(Base):
    """A restockable supply item (filament, plywood, vinyl, etc.).

    Tracked by quantity_on_hand vs low_stock_threshold so staff get an alert
    when something needs reordering. Distinct from Equipment (which is
    reservable and durable).
    """

    __tablename__ = "consumable_inventory"

    id: Mapped[int] = mapped_column("consumable_id", primary_key=True)

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    unit: Mapped[str] = mapped_column(String(20), nullable=False)

    # Numeric(10, 2) maps to DECIMAL(10,2) in Postgres. Stored as Decimal
    # in Python — do NOT convert to float on the way in/out, or you'll
    # introduce rounding drift over many restocks.
    quantity_on_hand: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        default=Decimal("0"),
    )
    low_stock_threshold: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        default=Decimal("0"),
    )

    # server_default=func.now() means Postgres sets the timestamp on INSERT.
    # The trigger in the migration handles UPDATE.
    last_updated: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
    )

    # Mirror the SQL CHECK constraints so SQLAlchemy DDL stays in sync if
    # you ever regenerate the schema via Base.metadata.create_all().
    __table_args__ = (
        CheckConstraint("quantity_on_hand >= 0", name="qty_non_negative"),
        CheckConstraint("low_stock_threshold >= 0", name="threshold_non_negative"),
    )

    @property
    def is_low_stock(self) -> bool:
        """Convenience flag for the admin UI."""
        return self.quantity_on_hand <= self.low_stock_threshold

def __repr__(self) -> str:
    return (
        f"<Consumable id={self.id} "
        f"name={self.name!r} qty={self.quantity_on_hand} {self.unit}>"
    )
