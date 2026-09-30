
import base64
import hashlib
import hmac
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from uuid import uuid4

import httpx
from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import database
from database import get_db_connection, hash_password

database.init_db()

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
UPLOADS_DIR = BASE_DIR / "uploads"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

APP_SECRET = os.getenv("APP_SECRET", "oceanwatch-development-secret-change-me")
TOKEN_TTL_SECONDS = 24 * 60 * 60
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
EXTERNAL_CACHE: dict[str, tuple[float, dict]] = {}

ALLOWED_STATUSES = {"Pending", "Verified", "Resolved", "Rejected"}
ALLOWED_SEVERITIES = {"Low", "Medium", "High", "Critical"}
ALLOWED_ROLES = {"user", "moderator", "admin"}


app = FastAPI(
    title="OceanGuard API",
    description="Ocean hazard reporting, live vessel tracking and marine conditions API.",
    version="2.0.0",
)

cors_origins = [
    item.strip()
    for item in os.getenv("CORS_ORIGINS", "*").split(",")
    if item.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")


class RegisterSchema(BaseModel):
    username: str = Field(min_length=3, max_length=40)
    email: str = Field(min_length=5, max_length=160)
    password: str = Field(min_length=6, max_length=128)
    full_name: str = Field(min_length=2, max_length=120)
    role: Optional[str] = "user"


class LoginSchema(BaseModel):
    login: str
    password: str


class StatusUpdateSchema(BaseModel):
    status: str
    admin_notes: str = ""
    severity: Optional[str] = None


class RoleUpdateSchema(BaseModel):
    role: str


class UserStatusUpdateSchema(BaseModel):
    status: str


class TrackingSchema(BaseModel):
    vessel_id: str = Field(min_length=2, max_length=48)
    latitude: float
    longitude: float
    accuracy: Optional[float] = None
    speed_knots: Optional[float] = None
    heading: Optional[float] = None


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_iso(value: Optional[datetime] = None) -> str:
    current = value or utc_now()
    return current.replace(microsecond=0).isoformat()


def validate_coordinates(latitude: float, longitude: float) -> None:
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise HTTPException(status_code=422, detail="Invalid latitude or longitude")


def issue_token(user_id: int, username: str) -> str:
    payload = f"{user_id}:{username}:{int(time.time()) + TOKEN_TTL_SECONDS}"
    encoded = base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")
    signature = hmac.new(
        APP_SECRET.encode("utf-8"),
        encoded.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return encoded + "." + signature


def verify_token(token: str) -> Optional[dict]:
    try:
        encoded, signature = token.split(".", 1)
        expected = hmac.new(
            APP_SECRET.encode("utf-8"),
            encoded.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        padding = "=" * (-len(encoded) % 4)
        raw = base64.urlsafe_b64decode((encoded + padding).encode("ascii")).decode("utf-8")
        user_id_text, username, exp_text = raw.rsplit(":", 2)
        if int(exp_text) < int(time.time()):
            return None
        return {"id": int(user_id_text), "username": username}
    except (ValueError, TypeError, UnicodeDecodeError):
        return None


def get_current_user(authorization: Optional[str] = Header(None)):
    if not authorization:
        return None

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None

    token_payload = verify_token(token.strip())
    if not token_payload:
        return None

    conn = get_db_connection()
    row = conn.execute(
        """
        SELECT id, username, email, role, full_name, status
        FROM users
        WHERE id = ?
        """,
        (token_payload["id"],),
    ).fetchone()
    conn.close()

    if not row or row["status"] != "active":
        return None
    return dict(row)


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if not user or user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Administrator access required")
    return user


def safe_filename(filename: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", os.path.basename(filename))
    return cleaned[:120] or "upload.bin"


async def fetch_open_meteo(url: str, params: dict, cache_key: str) -> dict:
    now = time.time()
    cached = EXTERNAL_CACHE.get(cache_key)
    if cached and now - cached[0] < 300:
        return cached[1]

    async with httpx.AsyncClient(timeout=12) as client:
        response = await client.get(
            url,
            params=params,
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()
        payload = response.json()

    EXTERNAL_CACHE[cache_key] = (now, payload)
    return payload


@app.get("/healthz")
def healthz():
    try:
        conn = get_db_connection()
        conn.execute("SELECT 1").fetchone()
        conn.close()
        return {"status": "ok", "service": "oceanguard", "time": utc_iso()}
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc


@app.get("/api/config")
def get_config():
    return {
        "app_name": "OceanGuard",
        "version": "2.0.0",
        "default_center": {"latitude": 11.15, "longitude": 79.95, "zoom": 7},
        "tracking_interval_seconds": 10,
        "stale_after_seconds": 180,
        "map": {
            "engine": "Leaflet + OpenStreetMap",
            "google_maps_link_supported": True,
        },
        "data_sources": [
            {"name": "Open-Meteo Weather", "url": "https://open-meteo.com/"},
            {
                "name": "Open-Meteo Marine",
                "url": "https://open-meteo.com/en/docs/marine-weather-api",
            },
            {
                "name": "OpenStreetMap",
                "url": "https://www.openstreetmap.org/",
            },
        ],
    }


@app.post("/api/auth/register")
def register(data: RegisterSchema):
    username = data.username.strip()
    email = data.email.strip().lower()
    full_name = data.full_name.strip()

    conn = get_db_connection()
    existing = conn.execute(
        """
        SELECT id
        FROM users
        WHERE lower(username) = lower(?) OR lower(email) = lower(?)
        """,
        (username, email),
    ).fetchone()
    if existing:
        conn.close()
        raise HTTPException(status_code=400, detail="Username or email already registered")

    cursor = conn.execute(
        """
        INSERT INTO users (username, email, password_hash, role, full_name)
        VALUES (?, ?, ?, 'user', ?)
        """,
        (username, email, hash_password(data.password), full_name),
    )
    conn.commit()
    user_id = cursor.lastrowid
    conn.close()

    return {
        "message": "Registration successful",
        "token": issue_token(user_id, username),
        "user": {
            "id": user_id,
            "username": username,
            "email": email,
            "role": "user",
            "full_name": full_name,
            "status": "active",
        },
    }


@app.post("/api/auth/login")
def login(data: LoginSchema):
    conn = get_db_connection()
    user = conn.execute(
        """
        SELECT id, username, email, role, full_name, status
        FROM users
        WHERE (lower(username) = lower(?) OR lower(email) = ?)
          AND password_hash = ?
        """,
        (
            data.login.strip(),
            data.login.strip().lower(),
            hash_password(data.password),
        ),
    ).fetchone()
    conn.close()

    if not user:
        raise HTTPException(status_code=401, detail="Invalid username/email or password")
    if user["status"] != "active":
        raise HTTPException(status_code=403, detail="Account is not active")

    return {
        "message": "Login successful",
        "token": issue_token(user["id"], user["username"]),
        "user": dict(user),
    }


@app.get("/api/auth/me")
def get_me(user: dict = Depends(get_current_user)):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {"user": user}


@app.get("/api/categories")
def get_categories():
    conn = get_db_connection()
    categories = [
        dict(row)
        for row in conn.execute("SELECT * FROM categories ORDER BY name").fetchall()
    ]
    conn.close()
    return {"categories": categories}


@app.get("/api/reports")
def get_reports(
    category: Optional[str] = None,
    status: Optional[str] = None,
    severity: Optional[str] = None,
    search: Optional[str] = None,
    user_id: Optional[int] = None,
    limit: int = Query(200, ge=1, le=500),
):
    conn = get_db_connection()
    query = """
        SELECT r.*,
               c.name AS category_name,
               c.icon AS category_icon,
               c.color AS category_color
        FROM reports r
        JOIN categories c ON r.category_id = c.id
        WHERE 1 = 1
    """
    params: list = []

    if category and category != "all":
        query += " AND r.category_id = ?"
        params.append(category)
    if status and status != "all":
        query += " AND r.status = ?"
        params.append(status)
    if severity and severity != "all":
        query += " AND r.severity = ?"
        params.append(severity)
    if user_id:
        query += " AND r.user_id = ?"
        params.append(user_id)
    if search:
        query += " AND (r.title LIKE ? OR r.description LIKE ? OR r.location_name LIKE ?)"
        term = "%" + search.strip() + "%"
        params.extend([term, term, term])

    query += " ORDER BY datetime(r.created_at) DESC LIMIT ?"
    params.append(limit)

    reports = [dict(row) for row in conn.execute(query, params).fetchall()]
    conn.close()
    return {"reports": reports}


@app.get("/api/reports/{report_id}")
def get_report_detail(report_id: int):
    conn = get_db_connection()
    report = conn.execute(
        """
        SELECT r.*, c.name AS category_name, c.icon AS category_icon, c.color AS category_color
        FROM reports r
        JOIN categories c ON r.category_id = c.id
        WHERE r.id = ?
        """,
        (report_id,),
    ).fetchone()
    conn.close()

    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return {"report": dict(report)}


@app.post("/api/reports")
async def create_report(
    title: str = Form(...),
    category_id: str = Form(...),
    description: str = Form(...),
    severity: str = Form(...),
    latitude: float = Form(...),
    longitude: float = Form(...),
    location_name: str = Form(...),
    author_name: str = Form("Anonymous"),
    reporter_contact: str = Form(""),
    observed_at: str = Form(""),
    image: Optional[UploadFile] = File(None),
    user: dict = Depends(get_current_user),
):
    validate_coordinates(latitude, longitude)

    if severity not in ALLOWED_SEVERITIES:
        raise HTTPException(status_code=422, detail="Invalid severity")

    conn = get_db_connection()
    category = conn.execute(
        "SELECT id FROM categories WHERE id = ?",
        (category_id,),
    ).fetchone()
    if not category:
        conn.close()
        raise HTTPException(status_code=422, detail="Invalid hazard category")

    safe_user_id = user["id"] if user else 1
    safe_author_name = (
        user["full_name"] if user else (author_name or "Anonymous").strip()[:120]
    )

    image_url = None
    if image and image.filename:
        allowed_types = {"image/jpeg", "image/png", "image/webp"}
        if image.content_type not in allowed_types:
            conn.close()
            raise HTTPException(
                status_code=415,
                detail="Only JPEG, PNG and WebP images are accepted",
            )

        content = await image.read()
        if len(content) > MAX_UPLOAD_BYTES:
            conn.close()
            raise HTTPException(status_code=413, detail="Image exceeds 5 MB")

        filename = (
            str(int(time.time()))
            + "_"
            + uuid4().hex[:10]
            + "_"
            + safe_filename(image.filename)
        )
        file_path = UPLOADS_DIR / filename
        with file_path.open("wb") as handle:
            handle.write(content)
        image_url = "/uploads/" + filename

    now = utc_iso()
    report_code = (
        "OW-" + utc_now().strftime("%Y%m%d") + "-" + uuid4().hex[:6].upper()
    )

    cursor = conn.execute(
        """
        INSERT INTO reports
        (report_code, title, category_id, description, severity, status,
         latitude, longitude, location_name, image_url, user_id, author_name,
         reporter_contact, source, is_demo, created_at, updated_at, observed_at)
        VALUES (?, ?, ?, ?, ?, 'Pending', ?, ?, ?, ?, ?, ?, ?, 'community', 0, ?, ?, ?)
        """,
        (
            report_code,
            title.strip()[:200],
            category_id,
            description.strip()[:5000],
            severity,
            latitude,
            longitude,
            location_name.strip()[:160],
            image_url,
            safe_user_id,
            safe_author_name,
            (reporter_contact or "").strip()[:80],
            now,
            now,
            observed_at.strip()[:80] or now,
        ),
    )
    report_id = cursor.lastrowid

    conn.execute(
        """
        INSERT INTO notifications (user_id, title, message, type, is_read)
        VALUES (?, ?, ?, 'info', 0)
        """,
        (
            safe_user_id,
            "Hazard report received",
            "Report " + report_code + " is stored and awaiting verification.",
        ),
    )
    conn.commit()
    conn.close()

    return {
        "message": "Report created successfully",
        "report_id": report_id,
        "report_code": report_code,
        "image_url": image_url,
        "status": "Pending",
    }


@app.patch("/api/reports/{report_id}")
def update_report_status(
    report_id: int,
    body: StatusUpdateSchema,
    admin: dict = Depends(require_admin),
):
    if body.status not in ALLOWED_STATUSES:
        raise HTTPException(status_code=422, detail="Invalid report status")
    if body.severity and body.severity not in ALLOWED_SEVERITIES:
        raise HTTPException(status_code=422, detail="Invalid severity")

    conn = get_db_connection()
    report = conn.execute(
        "SELECT * FROM reports WHERE id = ?",
        (report_id,),
    ).fetchone()
    if not report:
        conn.close()
        raise HTTPException(status_code=404, detail="Report not found")

    now = utc_iso()
    if body.severity:
        conn.execute(
            """
            UPDATE reports
            SET status = ?, admin_notes = ?, severity = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                body.status,
                body.admin_notes.strip()[:2000],
                body.severity,
                now,
                report_id,
            ),
        )
    else:
        conn.execute(
            """
            UPDATE reports
            SET status = ?, admin_notes = ?, updated_at = ?
            WHERE id = ?
            """,
            (body.status, body.admin_notes.strip()[:2000], now, report_id),
        )

    notif_type = "success" if body.status in {"Verified", "Resolved"} else "warning"
    conn.execute(
        """
        INSERT INTO notifications (user_id, title, message, type, is_read)
        VALUES (?, ?, ?, ?, 0)
        """,
        (
            report["user_id"],
            "Report status updated",
            "Report "
            + (report["report_code"] or ("#" + str(report_id)))
            + " is now "
            + body.status
            + ".",
            notif_type,
        ),
    )
    conn.commit()
    conn.close()

    return {
        "message": "Report updated",
        "updated_by": admin["username"],
        "status": body.status,
    }


@app.post("/api/reports/{report_id}/upvote")
def upvote_report(report_id: int):
    conn = get_db_connection()
    updated = conn.execute(
        "UPDATE reports SET upvotes = upvotes + 1 WHERE id = ?",
        (report_id,),
    ).rowcount
    if updated == 0:
        conn.close()
        raise HTTPException(status_code=404, detail="Report not found")

    row = conn.execute(
        "SELECT upvotes FROM reports WHERE id = ?",
        (report_id,),
    ).fetchone()
    conn.commit()
    conn.close()
    return {"message": "Upvoted", "upvotes": row["upvotes"]}


@app.delete("/api/reports/{report_id}")
def delete_report(report_id: int, admin: dict = Depends(require_admin)):
    conn = get_db_connection()
    row = conn.execute(
        "SELECT image_url FROM reports WHERE id = ?",
        (report_id,),
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Report not found")

    conn.execute("DELETE FROM reports WHERE id = ?", (report_id,))
    conn.commit()
    conn.close()

    if row["image_url"]:
        possible_path = BASE_DIR / row["image_url"].lstrip("/")
        if possible_path.exists() and possible_path.is_file():
            try:
                possible_path.unlink()
            except OSError:
                pass

    return {"message": "Report deleted", "deleted_by": admin["username"]}


@app.get("/api/analytics/stats")
def get_analytics_stats():
    conn = get_db_connection()

    total = conn.execute("SELECT COUNT(*) AS count FROM reports").fetchone()["count"]
    pending = conn.execute(
        "SELECT COUNT(*) AS count FROM reports WHERE status = 'Pending'"
    ).fetchone()["count"]
    verified = conn.execute(
        "SELECT COUNT(*) AS count FROM reports WHERE status = 'Verified'"
    ).fetchone()["count"]
    resolved = conn.execute(
        "SELECT COUNT(*) AS count FROM reports WHERE status = 'Resolved'"
    ).fetchone()["count"]

    active_alerts = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM reports
        WHERE status NOT IN ('Resolved', 'Rejected')
          AND severity IN ('High', 'Critical')
        """
    ).fetchone()["count"]

    week_start = utc_now() - timedelta(days=7)
    week_reports = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM reports
        WHERE datetime(created_at) >= datetime(?)
        """,
        (week_start.isoformat(),),
    ).fetchone()["count"]

    tracking_cutoff = (
        utc_now() - timedelta(seconds=180)
    ).isoformat()
    active_vessels = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM vessel_locations
        WHERE datetime(recorded_at) >= datetime(?)
        """,
        (tracking_cutoff,),
    ).fetchone()["count"]

    categories = [
        dict(row)
        for row in conn.execute(
            """
            SELECT c.id, c.name, c.color, COUNT(r.id) AS count
            FROM categories c
            LEFT JOIN reports r ON c.id = r.category_id
            GROUP BY c.id, c.name, c.color
            ORDER BY count DESC
            """
        ).fetchall()
    ]

    severities = {
        row["severity"]: row["count"]
        for row in conn.execute(
            "SELECT severity, COUNT(*) AS count FROM reports GROUP BY severity"
        ).fetchall()
    }

    trend = []
    for offset in range(6, -1, -1):
        day = (utc_now() - timedelta(days=offset)).date()
        next_day = day + timedelta(days=1)
        count = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM reports
            WHERE datetime(created_at) >= datetime(?)
              AND datetime(created_at) < datetime(?)
            """,
            (day.isoformat(), next_day.isoformat()),
        ).fetchone()["count"]
        trend.append({"date": day.isoformat(), "reports": count})

    conn.close()

    verification_rate = round(((verified + resolved) / total) * 100, 1) if total else 0

    return {
        "total_reports": total,
        "pending_reports": pending,
        "verified_reports": verified,
        "resolved_reports": resolved,
        "active_alerts": active_alerts,
        "reports_this_week": week_reports,
        "tracked_vessels": active_vessels,
        "verification_rate": verification_rate,
        "category_breakdown": categories,
        "severity_breakdown": severities,
        "recent_trend": trend,
    }


@app.get("/api/notifications")
def get_notifications(user: dict = Depends(get_current_user)):
    conn = get_db_connection()
    if user and user.get("role") == "admin":
        rows = conn.execute(
            "SELECT * FROM notifications ORDER BY datetime(created_at) DESC LIMIT 50"
        ).fetchall()
    elif user:
        rows = conn.execute(
            """
            SELECT *
            FROM notifications
            WHERE user_id = ? OR user_id IS NULL
            ORDER BY datetime(created_at) DESC
            LIMIT 20
            """,
            (user["id"],),
        ).fetchall()
    else:
        rows = []

    conn.close()
    return {"notifications": [dict(row) for row in rows]}


@app.post("/api/notifications/{notif_id}/read")
def mark_notification_read(
    notif_id: int,
    user: dict = Depends(get_current_user),
):
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    conn = get_db_connection()
    query = "UPDATE notifications SET is_read = 1 WHERE id = ?"
    params = [notif_id]
    if user.get("role") != "admin":
        query += " AND (user_id = ? OR user_id IS NULL)"
        params.append(user["id"])

    updated = conn.execute(query, params).rowcount
    conn.commit()
    conn.close()

    if updated == 0:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"message": "Notification marked as read"}


@app.post("/api/notifications/clear")
def clear_all_notifications(user: dict = Depends(get_current_user)):
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    conn = get_db_connection()
    if user.get("role") == "admin":
        conn.execute("UPDATE notifications SET is_read = 1")
    else:
        conn.execute(
            """
            UPDATE notifications
            SET is_read = 1
            WHERE user_id = ? OR user_id IS NULL
            """,
            (user["id"],),
        )

    conn.commit()
    conn.close()
    return {"message": "Notifications cleared"}


@app.get("/api/users")
def get_users(admin: dict = Depends(require_admin)):
    conn = get_db_connection()
    rows = conn.execute(
        """
        SELECT u.id, u.username, u.email, u.role, u.full_name, u.status, u.created_at,
               COUNT(r.id) AS report_count
        FROM users u
        LEFT JOIN reports r ON u.id = r.user_id
        GROUP BY u.id
        ORDER BY u.id ASC
        """
    ).fetchall()
    conn.close()

    return {"users": [dict(row) for row in rows]}


@app.patch("/api/users/{user_id}/role")
def update_user_role(
    user_id: int,
    body: RoleUpdateSchema,
    admin: dict = Depends(require_admin),
):
    if body.role not in ALLOWED_ROLES:
        raise HTTPException(status_code=422, detail="Invalid role")
    if user_id == admin["id"] and body.role != "admin":
        raise HTTPException(
            status_code=400,
            detail="You cannot remove your own administrator role",
        )

    conn = get_db_connection()
    updated = conn.execute(
        "UPDATE users SET role = ? WHERE id = ?",
        (body.role, user_id),
    ).rowcount
    conn.commit()
    conn.close()

    if updated == 0:
        raise HTTPException(status_code=404, detail="User not found")
    return {"message": "User role updated"}


@app.patch("/api/users/{user_id}/status")
def update_user_status(
    user_id: int,
    body: UserStatusUpdateSchema,
    admin: dict = Depends(require_admin),
):
    if body.status not in {"active", "suspended"}:
        raise HTTPException(status_code=422, detail="Invalid user status")
    if user_id == admin["id"] and body.status != "active":
        raise HTTPException(
            status_code=400,
            detail="You cannot suspend your current administrator session",
        )

    conn = get_db_connection()
    updated = conn.execute(
        "UPDATE users SET status = ? WHERE id = ?",
        (body.status, user_id),
    ).rowcount
    conn.commit()
    conn.close()

    if updated == 0:
        raise HTTPException(status_code=404, detail="User not found")
    return {"message": "User status updated"}


@app.get("/api/tracking")
def get_tracking(stale_after: int = Query(180, ge=30, le=600)):
    cutoff = (utc_now() - timedelta(seconds=stale_after)).isoformat()
    conn = get_db_connection()
    rows = conn.execute(
        """
        SELECT v.*, u.full_name
        FROM vessel_locations v
        LEFT JOIN users u ON u.id = v.user_id
        WHERE datetime(v.recorded_at) >= datetime(?)
        ORDER BY datetime(v.recorded_at) DESC
        """,
        (cutoff,),
    ).fetchall()
    conn.close()

    return {
        "locations": [dict(row) for row in rows],
        "stale_after_seconds": stale_after,
    }


@app.post("/api/tracking")
def update_tracking(data: TrackingSchema, user: dict = Depends(get_current_user)):
    validate_coordinates(data.latitude, data.longitude)

    vessel_id = data.vessel_id.strip().upper()
    if not re.match(r"^[A-Z0-9._-]{2,48}$", vessel_id):
        raise HTTPException(
            status_code=422,
            detail="Vessel ID may contain letters, numbers, dots, underscores and hyphens only",
        )

    if data.accuracy is not None and not (0 <= data.accuracy <= 100000):
        raise HTTPException(status_code=422, detail="Invalid accuracy")
    if data.speed_knots is not None and not (0 <= data.speed_knots <= 150):
        raise HTTPException(status_code=422, detail="Invalid speed")
    if data.heading is not None and not (0 <= data.heading <= 360):
        raise HTTPException(status_code=422, detail="Invalid heading")

    owner_id = user["id"] if user else None
    now = utc_iso()

    conn = get_db_connection()
    conn.execute(
        """
        INSERT INTO vessel_locations
        (vessel_id, user_id, latitude, longitude, accuracy, speed_knots, heading, is_demo, recorded_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)
        ON CONFLICT(vessel_id) DO UPDATE SET
            user_id = excluded.user_id,
            latitude = excluded.latitude,
            longitude = excluded.longitude,
            accuracy = excluded.accuracy,
            speed_knots = excluded.speed_knots,
            heading = excluded.heading,
            is_demo = 0,
            recorded_at = excluded.recorded_at
        """,
        (
            vessel_id,
            owner_id,
            data.latitude,
            data.longitude,
            data.accuracy,
            data.speed_knots,
            data.heading,
            now,
        ),
    )
    conn.commit()
    conn.close()

    return {
        "message": "Location updated",
        "vessel_id": vessel_id,
        "recorded_at": now,
    }


@app.delete("/api/tracking/{vessel_id}")
def stop_tracking(vessel_id: str, user: dict = Depends(get_current_user)):
    vessel_id = vessel_id.strip().upper()
    conn = get_db_connection()
    row = conn.execute(
        "SELECT user_id FROM vessel_locations WHERE vessel_id = ?",
        (vessel_id,),
    ).fetchone()

    if not row:
        conn.close()
        return {"message": "Tracking already stopped"}

    if (
        user
        and user.get("role") != "admin"
        and row["user_id"] not in {None, user["id"]}
    ):
        conn.close()
        raise HTTPException(
            status_code=403,
            detail="Not authorised to stop this tracker",
        )

    conn.execute(
        "DELETE FROM vessel_locations WHERE vessel_id = ?",
        (vessel_id,),
    )
    conn.commit()
    conn.close()

    return {"message": "Tracking stopped", "vessel_id": vessel_id}


@app.get("/api/weather")
async def get_weather(latitude: float = Query(...), longitude: float = Query(...)):
    validate_coordinates(latitude, longitude)
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "current": (
            "temperature_2m,apparent_temperature,relative_humidity_2m,"
            "precipitation,weather_code,wind_speed_10m,wind_gusts_10m,"
            "wind_direction_10m"
        ),
        "timezone": "auto",
        "forecast_days": 1,
    }

    try:
        payload = await fetch_open_meteo(
            "https://api.open-meteo.com/v1/forecast",
            params,
            "weather:" + str(round(latitude, 2)) + ":" + str(round(longitude, 2)),
        )
        return {
            "source": "Open-Meteo",
            "licence": "CC BY 4.0",
            "latitude": payload.get("latitude"),
            "longitude": payload.get("longitude"),
            "timezone": payload.get("timezone"),
            "current": payload.get("current", {}),
        }
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail="Weather provider unavailable",
        ) from exc


@app.get("/api/marine")
async def get_marine(latitude: float = Query(...), longitude: float = Query(...)):
    validate_coordinates(latitude, longitude)
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "current": (
            "wave_height,wave_direction,wave_period,wind_wave_height,"
            "swell_wave_height,sea_surface_temperature,ocean_current_velocity,"
            "ocean_current_direction"
        ),
        "hourly": "wave_height,swell_wave_height",
        "forecast_hours": 12,
        "timezone": "auto",
        "cell_selection": "sea",
    }

    try:
        payload = await fetch_open_meteo(
            "https://api.open-meteo.com/v1/marine",
            params,
            "marine:" + str(round(latitude, 2)) + ":" + str(round(longitude, 2)),
        )
        current = payload.get("current", {})
        hourly = payload.get("hourly", {})

        wave_values = [
            value
            for value in hourly.get("wave_height", [])
            if isinstance(value, (int, float))
        ]
        swell_values = [
            value
            for value in hourly.get("swell_wave_height", [])
            if isinstance(value, (int, float))
        ]

        current["next_12h_wave_peak_m"] = (
            round(max(wave_values), 2) if wave_values else None
        )
        current["next_12h_swell_peak_m"] = (
            round(max(swell_values), 2) if swell_values else None
        )

        return {
            "source": "Open-Meteo Marine",
            "licence": "Open-Meteo data attribution required",
            "latitude": payload.get("latitude"),
            "longitude": payload.get("longitude"),
            "timezone": payload.get("timezone"),
            "current": current,
        }
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail="Marine provider unavailable",
        ) from exc


@app.get("/")
def serve_index():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/{full_path:path}")
def serve_static(full_path: str):
    if full_path.startswith("api/") or full_path == "healthz":
        raise HTTPException(status_code=404, detail="Not found")

    target = STATIC_DIR / full_path
    if target.exists() and target.is_file():
        return FileResponse(str(target))

    return FileResponse(str(STATIC_DIR / "index.html"))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "backend:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        reload=os.getenv("RELOAD", "false").lower() == "true",
    )
