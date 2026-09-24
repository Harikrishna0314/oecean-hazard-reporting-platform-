import os
import shutil
import sqlite3
from typing import Optional, List
from datetime import datetime

from fastapi import FastAPI, HTTPException, Depends, Header, UploadFile, File, Form, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, EmailStr

import database
from database import get_db_connection, hash_password

# Initialize database
database.init_db()

app = FastAPI(
    title="OceanGuard API",
    description="REST API Backend for Ocean Hazard Reporting & Verification Platform",
    version="1.0.0"
)

# CORS middleware for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")
STATIC_DIR = os.path.join(BASE_DIR, "static")

os.makedirs(UPLOADS_DIR, exist_ok=True)
os.makedirs(STATIC_DIR, exist_ok=True)

app.mount("/uploads", StaticFiles(directory=UPLOADS_DIR), name="uploads")

# Pydantic Schemas
class RegisterSchema(BaseModel):
    username: str
    email: str
    password: str
    full_name: str
    role: Optional[str] = "user"

class LoginSchema(BaseModel):
    login: str  # username or email
    password: str

class StatusUpdateSchema(BaseModel):
    status: str
    admin_notes: Optional[str] = ""
    severity: Optional[str] = None

class RoleUpdateSchema(BaseModel):
    role: str

class UserStatusUpdateSchema(BaseModel):
    status: str

# Helper Auth token extractor (Simple Token mechanism)
def get_current_user(authorization: Optional[str] = Header(None)):
    if not authorization:
        return None
    token = authorization.replace("Bearer ", "").strip()
    conn = get_db_connection()
    cursor = conn.cursor()
    # Simple token: format "user_{id}_{username}" or check user id
    if token.startswith("user_"):
        parts = token.split("_")
        if len(parts) >= 2:
            try:
                user_id = int(parts[1])
                cursor.execute("SELECT id, username, email, role, full_name, status FROM users WHERE id = ?", (user_id,))
                user = cursor.fetchone()
                if user and user['status'] == 'active':
                    return dict(user)
            except ValueError:
                pass
    return None

# ================= AUTH ENDPOINTS =================

@app.post("/api/auth/register")
def register(data: RegisterSchema):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Check duplicate
    cursor.execute("SELECT id FROM users WHERE username = ? OR email = ?", (data.username, data.email))
    if cursor.fetchone():
        raise HTTPException(status_code=400, detail="Username or Email already registered")
    
    hashed = hash_password(data.password)
    cursor.execute(
        "INSERT INTO users (username, email, password_hash, role, full_name) VALUES (?, ?, ?, ?, ?)",
        (data.username, data.email, hashed, data.role or 'user', data.full_name)
    )
    conn.commit()
    user_id = cursor.lastrowid
    
    token = f"user_{user_id}_{data.username}"
    return {
        "message": "Registration successful",
        "token": token,
        "user": {
            "id": user_id,
            "username": data.username,
            "email": data.email,
            "role": data.role or 'user',
            "full_name": data.full_name
        }
    }

@app.post("/api/auth/login")
def login(data: LoginSchema):
    conn = get_db_connection()
    cursor = conn.cursor()
    hashed = hash_password(data.password)
    
    cursor.execute(
        "SELECT id, username, email, role, full_name, status FROM users WHERE (username = ? OR email = ?) AND password_hash = ?",
        (data.login, data.login, hashed)
    )
    user = cursor.fetchone()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username/email or password")
    
    if user['status'] != 'active':
        raise HTTPException(status_code=403, detail="Account suspended. Please contact administrator.")
    
    token = f"user_{user['id']}_{user['username']}"
    return {
        "message": "Login successful",
        "token": token,
        "user": dict(user)
    }

@app.get("/api/auth/me")
def get_me(user: dict = Depends(get_current_user)):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {"user": user}

# ================= CATEGORIES =================

@app.get("/api/categories")
def get_categories():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM categories")
    categories = [dict(row) for row in cursor.fetchall()]
    return {"categories": categories}

# ================= REPORTS ENDPOINTS =================

@app.get("/api/reports")
def get_reports(
    category: Optional[str] = None,
    status: Optional[str] = None,
    severity: Optional[str] = None,
    search: Optional[str] = None,
    user_id: Optional[int] = None
):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    query = """
        SELECT r.*, c.name as category_name, c.icon as category_icon, c.color as category_color
        FROM reports r
        JOIN categories c ON r.category_id = c.id
        WHERE 1=1
    """
    params = []
    
    if category and category != 'all':
        query += " AND r.category_id = ?"
        params.append(category)
        
    if status and status != 'all':
        query += " AND r.status = ?"
        params.append(status)

    if severity and severity != 'all':
        query += " AND r.severity = ?"
        params.append(severity)
        
    if user_id:
        query += " AND r.user_id = ?"
        params.append(user_id)
        
    if search:
        query += " AND (r.title LIKE ? OR r.description LIKE ? OR r.location_name LIKE ?)"
        term = f"%{search}%"
        params.extend([term, term, term])
        
    query += " ORDER BY r.created_at DESC"
    
    cursor.execute(query, params)
    reports = [dict(row) for row in cursor.fetchall()]
    return {"reports": reports}

@app.get("/api/reports/{report_id}")
def get_report_detail(report_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT r.*, c.name as category_name, c.icon as category_icon, c.color as category_color
        FROM reports r
        JOIN categories c ON r.category_id = c.id
        WHERE r.id = ?
    """, (report_id,))
    report = cursor.fetchone()
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
    user_id: int = Form(1),
    image: Optional[UploadFile] = File(None)
):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    image_url = "/uploads/oil_spill_ocean.png"  # Default fallback
    
    if image:
        filename = f"{int(datetime.now().timestamp())}_{image.filename.replace(' ', '_')}"
        file_path = os.path.join(UPLOADS_DIR, filename)
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(image.file, buffer)
        image_url = f"/uploads/{filename}"

    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute("""
        INSERT INTO reports (title, category_id, description, severity, status, latitude, longitude, location_name, image_url, user_id, author_name, created_at, updated_at)
        VALUES (?, ?, ?, ?, 'Pending', ?, ?, ?, ?, ?, ?, ?, ?)
    """, (title, category_id, description, severity, latitude, longitude, location_name, image_url, user_id, author_name, now_str, now_str))
    
    report_id = cursor.lastrowid
    
    # Trigger system notification for admins & user
    cursor.execute("""
        INSERT INTO notifications (user_id, title, message, type)
        VALUES (?, ?, ?, ?)
    """, (user_id, "Report Submitted", f"Your hazard report '{title}' was submitted and is pending verification.", "info"))
    
    conn.commit()
    return {"message": "Report created successfully", "report_id": report_id, "image_url": image_url}

@app.patch("/api/reports/{report_id}")
def update_report_status(report_id: int, body: StatusUpdateSchema):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM reports WHERE id = ?", (report_id,))
    report = cursor.fetchone()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
        
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    if body.severity:
        cursor.execute("""
            UPDATE reports SET status = ?, admin_notes = ?, severity = ?, updated_at = ? WHERE id = ?
        """, (body.status, body.admin_notes, body.severity, now_str, report_id))
    else:
        cursor.execute("""
            UPDATE reports SET status = ?, admin_notes = ?, updated_at = ? WHERE id = ?
        """, (body.status, body.admin_notes, now_str, report_id))

    # Send Notification to creator
    notif_type = 'success' if body.status == 'Verified' else ('info' if body.status == 'Resolved' else 'warning')
    cursor.execute("""
        INSERT INTO notifications (user_id, title, message, type)
        VALUES (?, ?, ?, ?)
    """, (report['user_id'], f"Report Status: {body.status}", f"Report '{report['title']}' has been updated to {body.status}.", notif_type))

    conn.commit()
    return {"message": f"Report status updated to {body.status}"}

@app.post("/api/reports/{report_id}/upvote")
def upvote_report(report_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE reports SET upvotes = upvotes + 1 WHERE id = ?", (report_id,))
    conn.commit()
    cursor.execute("SELECT upvotes FROM reports WHERE id = ?", (report_id,))
    upvotes = cursor.fetchone()['upvotes']
    return {"message": "Upvoted", "upvotes": upvotes}

@app.delete("/api/reports/{report_id}")
def delete_report(report_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM reports WHERE id = ?", (report_id,))
    conn.commit()
    return {"message": "Report deleted successfully"}

# ================= ANALYTICS =================

@app.get("/api/analytics/stats")
def get_analytics_stats():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Counts by status
    cursor.execute("SELECT status, COUNT(*) as count FROM reports GROUP BY status")
    status_counts = {row['status']: row['count'] for row in cursor.fetchall()}
    
    total = sum(status_counts.values())
    pending = status_counts.get('Pending', 0)
    verified = status_counts.get('Verified', 0)
    resolved = status_counts.get('Resolved', 0)
    
    # Category breakdown
    cursor.execute("""
        SELECT c.name, c.color, COUNT(r.id) as count
        FROM categories c
        LEFT JOIN reports r ON c.id = r.category_id
        GROUP BY c.id
    """)
    category_counts = [dict(row) for row in cursor.fetchall()]
    
    # Severity breakdown
    cursor.execute("SELECT severity, COUNT(*) as count FROM reports GROUP BY severity")
    severity_counts = {row['severity']: row['count'] for row in cursor.fetchall()}
    
    # Verification rate
    verification_rate = round((verified + resolved) / total * 100, 1) if total > 0 else 0
    
    return {
        "total_reports": total,
        "pending_reports": pending,
        "verified_reports": verified,
        "resolved_reports": resolved,
        "verification_rate": f"{verification_rate}%",
        "avg_resolution_hours": "4.2",
        "category_breakdown": category_counts,
        "severity_breakdown": severity_counts,
        "recent_trend": [
            {"month": "May", "reports": 12, "resolved": 10},
            {"month": "Jun", "reports": 18, "resolved": 15},
            {"month": "Jul", "reports": total, "resolved": resolved}
        ]
    }

# ================= NOTIFICATIONS =================

@app.get("/api/notifications")
def get_notifications():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM notifications ORDER BY created_at DESC LIMIT 20")
    notifs = [dict(row) for row in cursor.fetchall()]
    return {"notifications": notifs}

@app.post("/api/notifications/{notif_id}/read")
def mark_notification_read(notif_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE notifications SET is_read = 1 WHERE id = ?", (notif_id,))
    conn.commit()
    return {"message": "Notification marked as read"}

@app.post("/api/notifications/clear")
def clear_all_notifications():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE notifications SET is_read = 1")
    conn.commit()
    return {"message": "All notifications marked as read"}

# ================= USERS MANAGEMENT (ADMIN) =================

@app.get("/api/users")
def get_users():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT u.id, u.username, u.email, u.role, u.full_name, u.status, u.created_at,
               COUNT(r.id) as report_count
        FROM users u
        LEFT JOIN reports r ON u.id = r.user_id
        GROUP BY u.id
        ORDER BY u.id ASC
    """)
    users = [dict(row) for row in cursor.fetchall()]
    return {"users": users}

@app.patch("/api/users/{user_id}/role")
def update_user_role(user_id: int, body: RoleUpdateSchema):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET role = ? WHERE id = ?", (body.role, user_id))
    conn.commit()
    return {"message": f"User role updated to {body.role}"}

@app.patch("/api/users/{user_id}/status")
def update_user_status(user_id: int, body: UserStatusUpdateSchema):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET status = ? WHERE id = ?", (body.status, user_id))
    conn.commit()
    return {"message": f"User status updated to {body.status}"}

# Serve Frontend Index
@app.get("/")
def serve_index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))

@app.get("/{full_path:path}")
def serve_static(full_path: str):
    target_path = os.path.join(STATIC_DIR, full_path)
    if os.path.exists(target_path) and os.path.isfile(target_path):
        return FileResponse(target_path)
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
