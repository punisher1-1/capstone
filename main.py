"""
main.py — MakerSpaceHub FastAPI application.

Equipment, Member, Reservation, and CheckIn endpoints all talk to
PostgreSQL via SQLAlchemy. Login is currently mocked; will be tied
to the Member table later.
"""
from contextlib import asynccontextmanager
from datetime import date, datetime
from typing import Literal, Optional

from fastapi import FastAPI, Depends, Form, HTTPException, Query, status
from decimal import Decimal 
from fastapi.responses import HTMLResponse
from fastapi import Response  
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload
from starlette.requests import Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse

import models
from database import engine, get_db


# =================================================================
# Pydantic Schemas — request/response validation only
# =================================================================

# ---------- Equipment Schemas ----------
class EquipmentBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100,
                      description="Equipment name, e.g. '3D Printer A'")
    category: str = Field(..., description="Category, e.g. '3D Printing'")
    status: str = Field(default="available",
                        description="available | in_use | maintenance")
    location: Optional[str] = Field(default=None,
                                    description="Physical location in the makerspace")


class EquipmentCreate(EquipmentBase):
    pass


class EquipmentRead(EquipmentBase):
    id: int
    model_config = {"from_attributes": True}


# ---------- Member Schemas ----------
MembershipType = Literal["student", "staff", "community", "faculty"]


class MemberBase(BaseModel):
    first_name: str = Field(..., min_length=1, max_length=50)
    last_name: str = Field(..., min_length=1, max_length=50)
    email: EmailStr
    phone: Optional[str] = Field(default=None, max_length=20)
    membership_type: MembershipType = "student"
    join_date: Optional[date] = Field(
        default=None,
        description="Server defaults to today's date if not provided"
    )
    is_active: bool = True


class MemberCreate(MemberBase):
    pass


class MemberRead(MemberBase):
    id: int
    model_config = {"from_attributes": True}


# ---------- Reservation Schemas ----------
ReservationStatus = Literal["pending", "confirmed", "cancelled", "completed"]


class ReservationCreate(BaseModel):
    member_id: int
    equipment_id: int
    start_time: datetime
    end_time: datetime
    notes: Optional[str] = None


class ReservationUpdate(BaseModel):
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    status: Optional[ReservationStatus] = None
    notes: Optional[str] = None


class ReservationRead(BaseModel):
    id: int
    member_id: int
    equipment_id: int
    start_time: datetime
    end_time: datetime
    status: ReservationStatus
    notes: Optional[str] = None
    member_name: str
    equipment_name: str
    model_config = {"from_attributes": True}


# ---------- CheckIn Schemas ----------
class CheckInCreate(BaseModel):
    """Client → Server shape when checking a member in."""
    member_id: int
    purpose: Optional[str] = Field(default=None, max_length=100,
                                   description="Why the member is here today")
    reservation_id: Optional[int] = Field(
        default=None,
        description="Optional — link to a scheduled reservation"
    )


class CheckInRead(BaseModel):
    """Server → Client shape with member name and (if applicable) equipment."""
    id: int
    member_id: int
    member_name: str
    check_in_time: datetime
    check_out_time: Optional[datetime] = None
    purpose: Optional[str] = None
    reservation_id: Optional[int] = None
    equipment_name: Optional[str] = None  # populated when reservation_id is set
    model_config = {"from_attributes": True}


# =================================================================
# Lifespan
# =================================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"[startup] App ready. Engine connected to {engine.url.database}.")
    yield
    print("[shutdown] Goodbye.")


app = FastAPI(title="MakerSpaceHub API", lifespan=lifespan)
templates = Jinja2Templates(directory="templates")

# Serve the website (Unit 5 HTML pages, CSS, JS)
app.mount("/static", StaticFiles(directory="static"), name="static")

# Root redirect → landing page
@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/static/index.html")

# =================================================================
# Root + Auth (mocked)
# =================================================================
@app.get("/")
def read_root():
    return {"message": "Hello, MakerSpaceHub"}


MOCK_USERNAME = "admin"
MOCK_PASSWORD = "makerspace2026"


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html")


@app.post("/login")
def login_submit(
    response: Response,
    username: str = Form(...),
    password: str = Form(...),
):
    """
    Validate mock credentials and issue a session cookie.
    The cookie is HttpOnly so JavaScript on the page cannot read it —
    only the browser can send it back on subsequent requests.
    """
    if username == MOCK_USERNAME and password == MOCK_PASSWORD:
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=SESSION_COOKIE_VALUE,
            max_age=SESSION_MAX_AGE_SECONDS,
            httponly=True,    # JS can't read it → CSRF mitigations don't double up
            samesite="lax",   # cookie sent on top-level GETs, blocked on cross-site POSTs
            secure=False,     # flip to True once the app is behind HTTPS
        )
        return {"message": f"Welcome, {username}", "redirect": "/admin"}
    raise HTTPException(status_code=401, detail="Invalid username or password")

@app.post("/logout")
def logout(response: Response):
    """Clear the session cookie. JS frontend then redirects to /login."""
    response.delete_cookie(key=SESSION_COOKIE_NAME)
    return {"message": "Logged out", "redirect": "/login"}


@app.get("/me")
def whoami(request: Request):
    """
    Lightweight auth probe used by admin.html on page load.
    Returns 401 (not 200 with a 'logged_out' flag) so the JS check is dead simple:
    if /me 401s, redirect to /login.
    """
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token != SESSION_COOKIE_VALUE:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {"authenticated": True, "username": MOCK_USERNAME}


@app.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request):
    """
    Server-gated admin page. Replaces direct access to /static/admin.html.
    Note: we don't use Depends(require_admin) here because that would return
    JSON {"detail": "Not authenticated"} to a browser — we want a redirect
    to /login instead. So we inline the check.
    """
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token != SESSION_COOKIE_VALUE:
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(request, "admin.html")
# =================================================================
# Session cookie config (mock auth)
# =================================================================
# This is intentionally a fixed token, not a signed JWT. The capstone scope
# is "demonstrate the auth wiring pattern"; graduating to a real per-user
# token with bcrypt-hashed passwords against the member table is documented
# as post-prototype work.
SESSION_COOKIE_NAME = "msh_session"
SESSION_COOKIE_VALUE = "admin-mock-session-v1"
SESSION_MAX_AGE_SECONDS = 60 * 60 * 8  # 8 hours


def require_admin(request: Request):
    """
    FastAPI dependency. Attach to any route that requires admin login:

        @app.post("/equipment", dependencies=[Depends(require_admin)])

    Reads the session cookie set by POST /login. Raises 401 if missing
    or wrong. Returns a minimal user dict so handlers that want it can
    accept `user: dict = Depends(require_admin)`.
    """
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token != SESSION_COOKIE_VALUE:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {"username": MOCK_USERNAME}
# =================================================================
# Equipment CRUD
# =================================================================
@app.get("/equipment", response_model=list[EquipmentRead])
def list_equipment(db: Session = Depends(get_db)):
    return db.scalars(select(models.Equipment)).all()


@app.get("/equipment/{equipment_id}", response_model=EquipmentRead)
def get_equipment(equipment_id: int, db: Session = Depends(get_db)):
    eq = db.get(models.Equipment, equipment_id)
    if eq is None:
        raise HTTPException(status_code=404,
                            detail=f"Equipment {equipment_id} not found")
    return eq


@app.post("/equipment", response_model=EquipmentRead,
          status_code=status.HTTP_201_CREATED,
          dependencies=[Depends(require_admin)])
def create_equipment(item: EquipmentCreate, db: Session = Depends(get_db)):
    eq = models.Equipment(**item.model_dump())
    db.add(eq)
    db.commit()
    db.refresh(eq)
    return eq


@app.put("/equipment/{equipment_id}", response_model=EquipmentRead,
         dependencies=[Depends(require_admin)])
def update_equipment(equipment_id: int, item: EquipmentCreate,
                     db: Session = Depends(get_db)):
    eq = db.get(models.Equipment, equipment_id)
    if eq is None:
        raise HTTPException(status_code=404,
                            detail=f"Equipment {equipment_id} not found")
    for key, value in item.model_dump().items():
        setattr(eq, key, value)
    db.commit()
    db.refresh(eq)
    return eq


@app.delete("/equipment/{equipment_id}",
            status_code=status.HTTP_204_NO_CONTENT,
            dependencies=[Depends(require_admin)])
def delete_equipment(equipment_id: int, db: Session = Depends(get_db)):
    eq = db.get(models.Equipment, equipment_id)
    if eq is None:
        raise HTTPException(status_code=404,
                            detail=f"Equipment {equipment_id} not found")
    db.delete(eq)
    db.commit()
    return None


# =================================================================
# Member CRUD
# =================================================================
# --- LIST: hide inactive members by default ----------------------------------
@app.get("/members", response_model=list[MemberRead])
def list_members(
    include_inactive: bool = False,
    db: Session = Depends(get_db),
):
    stmt = select(models.Member).order_by(models.Member.id)
    if not include_inactive:
        stmt = stmt.where(models.Member.is_active == True)
    return db.scalars(stmt).all()


@app.get("/members/{member_id}", response_model=MemberRead)
def get_member(member_id: int, db: Session = Depends(get_db)):
    member = db.get(models.Member, member_id)
    if member is None:
        raise HTTPException(status_code=404,
                            detail=f"Member {member_id} not found")
    return member


@app.post("/members", response_model=MemberRead,
          status_code=status.HTTP_201_CREATED,
          dependencies=[Depends(require_admin)])
def create_member(item: MemberCreate, db: Session = Depends(get_db)):
    data = item.model_dump()
    if data["join_date"] is None:
        data["join_date"] = date.today()
    member = models.Member(**data)
    try:
        db.add(member)
        db.commit()
        db.refresh(member)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"A member with email '{item.email}' already exists"
        )
    return member

@app.post("/members/{member_id}/reactivate", response_model=MemberRead,
          dependencies=[Depends(require_admin)])
def reactivate_member(member_id: int, db: Session = Depends(get_db)):
    member = db.get(models.Member, member_id)
    if member is None:
        raise HTTPException(status_code=404,
                            detail=f"Member {member_id} not found")
    if member.is_active:
        raise HTTPException(status_code=409,
                            detail=f"Member {member_id} is already active")
    member.is_active = True
    db.commit()
    db.refresh(member)
    return member

@app.put("/members/{member_id}", response_model=MemberRead,
         dependencies=[Depends(require_admin)])
def update_member(member_id: int, item: MemberCreate,
                  db: Session = Depends(get_db)):
    member = db.get(models.Member, member_id)
    if member is None:
        raise HTTPException(status_code=404,
                            detail=f"Member {member_id} not found")
    data = item.model_dump()
    if data["join_date"] is None:
        data["join_date"] = member.join_date
    for key, value in data.items():
        setattr(member, key, value)
    try:
        db.commit()
        db.refresh(member)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"A member with email '{item.email}' already exists"
        )
    return member


# --- DELETE: soft delete instead of removing the row -------------------------
@app.delete("/members/{member_id}",
            status_code=status.HTTP_204_NO_CONTENT,
            dependencies=[Depends(require_admin)])
def delete_member(member_id: int, db: Session = Depends(get_db)):
    member = db.get(models.Member, member_id)
    if member is None:
        raise HTTPException(status_code=404,
                            detail=f"Member {member_id} not found")
    if not member.is_active:
        raise HTTPException(status_code=409,
                            detail=f"Member {member_id} is already inactive")
    member.is_active = False
    db.commit()
    return None


# =================================================================
# Reservation
# =================================================================
def _has_conflict(
    db: Session,
    equipment_id: int,
    start: datetime,
    end: datetime,
    ignore_id: Optional[int] = None,
) -> bool:
    """True if [start, end) overlaps any pending/confirmed reservation."""
    stmt = (
        select(models.Reservation.id)
        .where(
            models.Reservation.equipment_id == equipment_id,
            models.Reservation.status.in_(["pending", "confirmed"]),
            models.Reservation.start_time < end,
            models.Reservation.end_time > start,
        )
        .limit(1)
    )
    if ignore_id is not None:
        stmt = stmt.where(models.Reservation.id != ignore_id)
    return db.scalar(stmt) is not None


@app.get("/reservations", response_model=list[ReservationRead])
def list_reservations(
    member_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    stmt = (
        select(models.Reservation)
        .options(
            selectinload(models.Reservation.member),
            selectinload(models.Reservation.equipment),
        )
        .order_by(models.Reservation.start_time.desc())
    )
    if member_id is not None:
        stmt = stmt.where(models.Reservation.member_id == member_id)
    return db.scalars(stmt).all()


@app.get("/reservations/{reservation_id}", response_model=ReservationRead)
def get_reservation(reservation_id: int, db: Session = Depends(get_db)):
    res = db.get(models.Reservation, reservation_id)
    if res is None:
        raise HTTPException(status_code=404,
                            detail=f"Reservation {reservation_id} not found")
    return res


@app.post("/reservations", response_model=ReservationRead,
          status_code=status.HTTP_201_CREATED)
def create_reservation(item: ReservationCreate, db: Session = Depends(get_db)):
    if item.end_time <= item.start_time:
        raise HTTPException(status_code=400,
                            detail="end_time must be after start_time")

    member = db.get(models.Member, item.member_id)
    if member is None:
        raise HTTPException(status_code=404,
                            detail=f"Member {item.member_id} not found")

    equipment = db.get(models.Equipment, item.equipment_id)
    if equipment is None:
        raise HTTPException(status_code=404,
                            detail=f"Equipment {item.equipment_id} not found")
    if equipment.status != "available":
        raise HTTPException(
            status_code=400,
            detail=f"Equipment is currently {equipment.status} and cannot be reserved"
        )

    if _has_conflict(db, item.equipment_id, item.start_time, item.end_time):
        raise HTTPException(
            status_code=409,
            detail="Time slot conflicts with an existing reservation"
        )

    reservation = models.Reservation(
        member_id=item.member_id,
        equipment_id=item.equipment_id,
        start_time=item.start_time,
        end_time=item.end_time,
        notes=item.notes,
        status="confirmed",
    )
    db.add(reservation)
    db.commit()
    db.refresh(reservation)
    return reservation


@app.patch("/reservations/{reservation_id}", response_model=ReservationRead)
def update_reservation(reservation_id: int, item: ReservationUpdate,
                       db: Session = Depends(get_db)):
    res = db.get(models.Reservation, reservation_id)
    if res is None:
        raise HTTPException(status_code=404,
                            detail=f"Reservation {reservation_id} not found")

    new_start = item.start_time if item.start_time is not None else res.start_time
    new_end = item.end_time if item.end_time is not None else res.end_time

    if item.start_time is not None or item.end_time is not None:
        if new_end <= new_start:
            raise HTTPException(status_code=400,
                                detail="end_time must be after start_time")
        if _has_conflict(db, res.equipment_id, new_start, new_end,
                         ignore_id=reservation_id):
            raise HTTPException(status_code=409,
                                detail="New time conflicts with another reservation")

    for key, value in item.model_dump(exclude_unset=True).items():
        setattr(res, key, value)

    db.commit()
    db.refresh(res)
    return res


@app.delete("/reservations/{reservation_id}", response_model=ReservationRead)
def cancel_reservation(reservation_id: int, db: Session = Depends(get_db)):
    res = db.get(models.Reservation, reservation_id)
    if res is None:
        raise HTTPException(status_code=404,
                            detail=f"Reservation {reservation_id} not found")
    res.status = "cancelled"
    db.commit()
    db.refresh(res)
    return res


# =================================================================
# CheckIn
# =================================================================
@app.get("/checkins", response_model=list[CheckInRead])
def list_checkins(
    active: bool = False,
    db: Session = Depends(get_db),
):
    """
    List today's check-ins, newest first.

    Query parameters:
      active=true  → only those still checked in (no check_out_time set)
      active=false → all of today's check-ins, including completed ones (default)

    Eagerly loads member and (if present) the linked reservation's equipment,
    so member_name and equipment_name resolve in a single follow-up query.
    """
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    stmt = (
        select(models.CheckIn)
        .options(
            selectinload(models.CheckIn.member),
            # Nested eager-load: checkin → reservation → equipment.
            # Avoids N+1 when populating equipment_name for many rows.
            selectinload(models.CheckIn.reservation)
            .selectinload(models.Reservation.equipment),
        )
        .where(models.CheckIn.check_in_time >= today_start)
        .order_by(models.CheckIn.check_in_time.desc())
    )

    if active:
        # IS NULL check — using SQLAlchemy's .is_(None) which generates
        # 'check_out_time IS NULL' in SQL. Don't use == None; SQLAlchemy's
        # comparison operators don't work that way.
        stmt = stmt.where(models.CheckIn.check_out_time.is_(None))

    return db.scalars(stmt).all()


@app.get("/checkins/{checkin_id}", response_model=CheckInRead)
def get_checkin(checkin_id: int, db: Session = Depends(get_db)):
    checkin = db.get(models.CheckIn, checkin_id)
    if checkin is None:
        raise HTTPException(status_code=404,
                            detail=f"Check-in {checkin_id} not found")
    return checkin


@app.post("/checkins", response_model=CheckInRead,
          status_code=status.HTTP_201_CREATED)
def check_in(item: CheckInCreate, db: Session = Depends(get_db)):
    """
    Staff checks a member into the makerspace.

    check_in_time is set automatically by the database (server_default).
    If reservation_id is supplied, validates the reservation exists and
    belongs to the same member.
    """
    member = db.get(models.Member, item.member_id)
    if member is None:
        raise HTTPException(status_code=404,
                            detail=f"Member {item.member_id} not found")

    if item.reservation_id is not None:
        reservation = db.get(models.Reservation, item.reservation_id)
        if reservation is None:
            raise HTTPException(
                status_code=404,
                detail=f"Reservation {item.reservation_id} not found"
            )
        if reservation.member_id != item.member_id:
            raise HTTPException(
                status_code=400,
                detail="Reservation does not belong to this member"
            )

    checkin = models.CheckIn(
        member_id=item.member_id,
        purpose=item.purpose,
        reservation_id=item.reservation_id,
    )
    db.add(checkin)
    db.commit()
    db.refresh(checkin)
    return checkin


@app.post("/checkins/{checkin_id}/checkout", response_model=CheckInRead)
def check_out(checkin_id: int, db: Session = Depends(get_db)):
    """
    Staff checks a member out of the makerspace by stamping check_out_time.
    Returns 400 if the member was already checked out.
    """
    checkin = db.get(models.CheckIn, checkin_id)
    if checkin is None:
        raise HTTPException(status_code=404,
                            detail=f"Check-in {checkin_id} not found")
    if checkin.check_out_time is not None:
        raise HTTPException(
            status_code=400,
            detail="Member has already been checked out"
        )

    checkin.check_out_time = datetime.now()
    db.commit()
    db.refresh(checkin)
    return checkin

"""
Consumable Pydantic schemas + CRUD routes for main.py.

"""

# =================================================================
# Pydantic Schemas — Consumable
# (Paste after the CheckIn schemas block.)
# =================================================================

class ConsumableBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100,
                      description="Item name, e.g. 'PLA Filament White 1.75mm'")
    category: str = Field(..., min_length=1, max_length=50,
                          description="Category, e.g. 'Filament', 'Wood', 'Electronics'")
    unit: str = Field(..., min_length=1, max_length=20,
                      description="Unit of measure: kg, sheet, roll, piece, meter")
    quantity_on_hand: Decimal = Field(
        ..., ge=0, max_digits=10, decimal_places=2,
        description="Current stock on hand, in `unit` units"
    )
    low_stock_threshold: Decimal = Field(
        ..., ge=0, max_digits=10, decimal_places=2,
        description="Alert fires when quantity_on_hand falls at or below this"
    )


class ConsumableCreate(ConsumableBase):
    pass


class ConsumableUpdate(BaseModel):
    """Partial update — every field optional. Common use is restocking
    (PATCH with just quantity_on_hand)."""
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    category: Optional[str] = Field(default=None, min_length=1, max_length=50)
    unit: Optional[str] = Field(default=None, min_length=1, max_length=20)
    quantity_on_hand: Optional[Decimal] = Field(
        default=None, ge=0, max_digits=10, decimal_places=2
    )
    low_stock_threshold: Optional[Decimal] = Field(
        default=None, ge=0, max_digits=10, decimal_places=2
    )


class ConsumableRead(ConsumableBase):
    id: int
    last_updated: datetime
    is_low_stock: bool   # populated from the Consumable.is_low_stock @property
    model_config = {"from_attributes": True}


# =================================================================
# Consumable CRUD
# (Paste after the CheckIn routes block.)
# =================================================================
@app.get("/consumables", response_model=list[ConsumableRead])
def list_consumables(
    category: Optional[str] = None,
    low_stock_only: bool = False,
    db: Session = Depends(get_db),
):
    """
    List consumables, ordered by category then name.

    Query parameters:
      category=Filament       → filter to one category
      low_stock_only=true     → only items at or below threshold (reorder list)
    """
    stmt = select(models.Consumable).order_by(
        models.Consumable.category,
        models.Consumable.name,
    )
    if category:
        stmt = stmt.where(models.Consumable.category == category)
    if low_stock_only:
        # SQL-level filter — much faster than fetching all rows and
        # filtering in Python, especially as inventory grows.
        stmt = stmt.where(
            models.Consumable.quantity_on_hand
            <= models.Consumable.low_stock_threshold
        )
    return db.scalars(stmt).all()


@app.get("/consumables/{consumable_id}", response_model=ConsumableRead)
def get_consumable(consumable_id: int, db: Session = Depends(get_db)):
    consumable = db.get(models.Consumable, consumable_id)
    if consumable is None:
        raise HTTPException(status_code=404,
                            detail=f"Consumable {consumable_id} not found")
    return consumable


@app.post("/consumables", response_model=ConsumableRead,
          status_code=status.HTTP_201_CREATED,
          dependencies=[Depends(require_admin)])
def create_consumable(item: ConsumableCreate, db: Session = Depends(get_db)):
    consumable = models.Consumable(**item.model_dump())
    db.add(consumable)
    db.commit()
    db.refresh(consumable)
    return consumable


@app.patch("/consumables/{consumable_id}", response_model=ConsumableRead,
           dependencies=[Depends(require_admin)])
def update_consumable(consumable_id: int, item: ConsumableUpdate,
                      db: Session = Depends(get_db)):
    """Partial update. Common use: PATCH with just quantity_on_hand to restock."""
    consumable = db.get(models.Consumable, consumable_id)
    if consumable is None:
        raise HTTPException(status_code=404,
                            detail=f"Consumable {consumable_id} not found")

    data = item.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=400, detail="No fields to update")

    for key, value in data.items():
        setattr(consumable, key, value)

    # last_updated is bumped by the Postgres trigger trg_consumable_touch().
    # Don't set it here — one source of truth.
    db.commit()
    db.refresh(consumable)
    return consumable


@app.delete("/consumables/{consumable_id}",
            status_code=status.HTTP_204_NO_CONTENT,
            dependencies=[Depends(require_admin)])
def delete_consumable(consumable_id: int, db: Session = Depends(get_db)):
    """Hard delete. Equipment uses soft-delete (status='retired'); consumables
    don't have a status field, so a hard delete is fine — empty items can
    just be removed."""
    consumable = db.get(models.Consumable, consumable_id)
    if consumable is None:
        raise HTTPException(status_code=404,
                            detail=f"Consumable {consumable_id} not found")
    db.delete(consumable)
    db.commit()
    return None
