import os
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, Header
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy.orm import Session
from database import Base, engine, get_db, SessionLocal
from models import User, Ticket, TicketActivity
from storage import save_attachment, get_attachment_download_target, UPLOAD_DIR
from security import (
    hash_password,
    verify_password,
    create_access_token,
    verify_access_token,
)

logger = logging.getLogger(__name__)

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Project TicketDesk")


@app.middleware("http")
async def proxy_headers_middleware(request, call_next):
    """Support reverse proxy TLS termination (AWS ALB / Nginx) via X-Forwarded-Proto."""
    proto = request.headers.get("x-forwarded-proto")
    if proto:
        request.scope["scheme"] = proto
    response = await call_next(request)
    return response

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

VALID_STATUSES = ["Open", "In Progress", "Resolved", "Closed"]
VALID_CATEGORIES = ["Hardware", "Software", "Network", "Email", "Account Access"]
VALID_ROLES = ["Admin", "Support Engineer", "User"]

# SEC-01: Insecure dev header authentication is strictly disabled by default.
# It can only be enabled in isolated dev/testing environments by explicitly setting ALLOW_DEV_HEADER_AUTH=true.
ALLOW_DEV_HEADER_AUTH = os.getenv("ALLOW_DEV_HEADER_AUTH", "false").lower() in ("true", "1", "yes")
if ALLOW_DEV_HEADER_AUTH:
    logger.warning(
        "SECURITY WARNING: ALLOW_DEV_HEADER_AUTH is enabled. "
        "Insecure X-Username header authentication is active. Do NOT use this in production!"
    )

# Seed default accounts if database is empty and upgrade existing plaintext passwords
def seed_users():
    db = SessionLocal()
    try:
        # Check and upgrade any legacy plaintext passwords to secure PBKDF2 hashes
        all_users = db.query(User).all()
        if all_users:
            updated = False
            for u in all_users:
                if not u.password.startswith("pbkdf2_sha256$"):
                    u.password = hash_password(u.password)
                    updated = True
            if updated:
                db.commit()
        else:
            admin_user = os.getenv("ADMIN_USERNAME", "admin").strip()
            admin_pass = os.getenv("ADMIN_PASSWORD", "admin123")
            seed_demo = os.getenv("SEED_DEMO_ACCOUNTS", "true").lower() in ("true", "1", "yes")

            users_to_seed = [
                User(username=admin_user, password=hash_password(admin_pass), role="Admin"),
            ]
            if seed_demo:
                users_to_seed.extend([
                    User(username="eng1", password=hash_password("eng123"), role="Support Engineer"),
                    User(username="eng2", password=hash_password("eng123"), role="Support Engineer"),
                    User(username="user1", password=hash_password("user123"), role="User"),
                ])
            db.add_all(users_to_seed)
            db.commit()
    finally:
        db.close()

seed_users()

class LoginRequest(BaseModel):
    username: str
    password: str

class CreateUserRequest(BaseModel):
    username: str
    password: str
    role: str = "User"

class StatusUpdate(BaseModel):
    status: str

class AssignRequest(BaseModel):
    assigned_to: str | None = None

def get_current_user(
    authorization: str | None = Header(None),
    x_username: str | None = Header(None),
    db: Session = Depends(get_db),
) -> User:
    # 1. Bearer Token Authentication (Secure Standard)
    if authorization and authorization.strip():
        auth_str = authorization.strip()
        if not auth_str.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Invalid authorization scheme. Bearer token required.")
        token = auth_str.split(" ", 1)[1].strip()
        payload = verify_access_token(token)
        if not payload or not payload.get("sub"):
            raise HTTPException(status_code=401, detail="Invalid or expired access token.")
        user = db.query(User).filter(User.username == payload["sub"]).first()
        if not user:
            raise HTTPException(status_code=401, detail="User associated with token not found.")
        return user

    # 2. Controlled Dev Header Authentication (Only when explicitly enabled for test compatibility)
    if ALLOW_DEV_HEADER_AUTH and x_username and x_username.strip():
        user = db.query(User).filter(User.username == x_username.strip()).first()
        if not user:
            raise HTTPException(status_code=401, detail="Invalid user.")
        return user

    raise HTTPException(status_code=401, detail="Not authenticated. Bearer token required.")

def log_activity(db: Session, ticket_id: int, actor: str, action: str):
    db.add(TicketActivity(ticket_id=ticket_id, actor=actor, action=action))

@app.get("/")
def serve_frontend():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))

@app.post("/api/login")
def login(creds: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == creds.username.strip()).first()
    if not user or not verify_password(creds.password, user.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Seamlessly upgrade legacy plaintext password to secure PBKDF2 hash on login
    if not user.password.startswith("pbkdf2_sha256$"):
        user.password = hash_password(creds.password)
        db.commit()

    access_token = create_access_token({"sub": user.username, "role": user.role})
    return {
        "message": "Login successful",
        "access_token": access_token,
        "token_type": "bearer",
        "username": user.username,
        "role": user.role,
    }

@app.post("/api/register")
def register(creds: LoginRequest, db: Session = Depends(get_db)):
    username = creds.username.strip()
    password = creds.password.strip()
    if not username or len(password) < 4:
        raise HTTPException(
            status_code=400,
            detail="Username is required and password must be at least 4 characters",
        )
    if db.query(User).filter(User.username == username).first():
        raise HTTPException(status_code=400, detail="Username already exists")

    # Always force role="User" on self-signup and hash password securely
    new_user = User(username=username, password=hash_password(password), role="User")
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    access_token = create_access_token({"sub": new_user.username, "role": new_user.role})
    return {
        "message": "Account created successfully",
        "access_token": access_token,
        "token_type": "bearer",
        "username": new_user.username,
        "role": new_user.role,
    }

# --- User Management ---
@app.get("/api/users")
def list_users(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.role == "User":
        raise HTTPException(status_code=403, detail="Users do not have permission to list accounts")
    users = db.query(User).all()
    return [{"id": u.id, "username": u.username, "role": u.role} for u in users]

@app.post("/api/users")
def create_user(payload: CreateUserRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.role != "Admin":
        raise HTTPException(status_code=403, detail="Only Admins can create users")
    if payload.role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail="Invalid role")
    if db.query(User).filter(User.username == payload.username.strip()).first():
        raise HTTPException(status_code=400, detail="Username already exists")
    user = User(username=payload.username.strip(), password=hash_password(payload.password), role=payload.role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"id": user.id, "username": user.username, "role": user.role}

# --- Enhanced Dashboard (Scoped to own tickets for regular Users) ---
@app.get("/api/dashboard")
def get_dashboard(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = db.query(Ticket)
    if current_user.role == "User":
        query = query.filter(Ticket.created_by == current_user.username)
    tickets = query.all()

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    recent_cutoff = now - timedelta(hours=24)

    summary = {status: 0 for status in VALID_STATUSES}
    high_priority = 0
    assigned_to_me = 0
    recently_created = 0
    awaiting_resolution = 0

    for t in tickets:
        if t.status in summary:
            summary[t.status] += 1
        if t.priority == "High" and t.status not in ("Resolved", "Closed"):
            high_priority += 1
        if t.assigned_to == current_user.username:
            assigned_to_me += 1
        if t.created_at and t.created_at >= recent_cutoff:
            recently_created += 1
        if t.status in ("Open", "In Progress"):
            awaiting_resolution += 1

    return {
        "status_counts": {**summary, "Total": len(tickets)},
        "highlights": {
            "high_priority": high_priority,
            "assigned_to_me": assigned_to_me,
            "recently_created": recently_created,
            "awaiting_resolution": awaiting_resolution,
        },
    }

# --- Tickets CRUD, Details, Assignment & History ---
@app.get("/api/tickets")
def list_tickets(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = db.query(Ticket)
    if current_user.role == "User":
        query = query.filter(Ticket.created_by == current_user.username)
    return query.order_by(Ticket.id.desc()).all()

@app.get("/api/tickets/{ticket_id}")
def get_ticket_details(ticket_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if current_user.role == "User" and ticket.created_by != current_user.username:
        raise HTTPException(status_code=403, detail="Users can only view their own tickets")

    activities = (
        db.query(TicketActivity)
        .filter(TicketActivity.ticket_id == ticket_id)
        .order_by(TicketActivity.timestamp.desc())
        .all()
    )
    return {
        "id": ticket.id,
        "title": ticket.title,
        "description": ticket.description,
        "category": ticket.category,
        "priority": ticket.priority,
        "status": ticket.status,
        "attachment": ticket.attachment,
        "created_by": ticket.created_by,
        "assigned_to": ticket.assigned_to,
        "created_at": ticket.created_at,
        "activities": [
            {"actor": a.actor, "action": a.action, "timestamp": a.timestamp}
            for a in activities
        ],
    }

@app.post("/api/tickets")
def create_ticket(
    title: str = Form(...),
    description: str = Form(...),
    category: str = Form("Software"),
    priority: str = Form("Medium"),
    file: UploadFile = File(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if category not in VALID_CATEGORIES:
        raise HTTPException(status_code=400, detail="Invalid category")

    # Step 1: Validate and save attachment using storage helper
    attachment_ref = None
    local_saved_path = None
    if file and file.filename:
        attachment_ref, local_saved_path = save_attachment(file)

    # Step 2: Store ticket record in database with rollback and file cleanup safety
    try:
        ticket = Ticket(
            title=title,
            description=description,
            category=category,
            priority=priority,
            status="Open",
            attachment=attachment_ref,
            created_by=current_user.username,
        )
        db.add(ticket)
        db.commit()
        db.refresh(ticket)

        log_activity(db, ticket.id, current_user.username, f"Created ticket ({category} | {priority} priority)")
        db.commit()
        return {
            "id": ticket.id,
            "title": ticket.title,
            "description": ticket.description,
            "category": ticket.category,
            "priority": ticket.priority,
            "status": ticket.status,
            "attachment": ticket.attachment,
            "created_by": ticket.created_by,
            "assigned_to": ticket.assigned_to,
            "created_at": ticket.created_at,
        }
    except Exception:
        db.rollback()
        # Clean up orphaned local file if database transaction failed
        if local_saved_path and os.path.exists(local_saved_path):
            try:
                os.remove(local_saved_path)
            except Exception:
                pass
        raise

@app.get("/api/tickets/{ticket_id}/attachment")
def download_ticket_attachment(
    ticket_id: int,
    redirect: bool = True,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Authenticated attachment retrieval endpoint.
    - Admins and Support Engineers can access any ticket's attachment.
    - Regular Users can only access attachments belonging to tickets they created.
    - Redirects to a 15-minute S3 pre-signed URL for cloud attachments (or returns JSON if redirect=False).
    - Safely returns a FileResponse for local file attachments.
    """
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    # Enforce Role-Based Access Control
    if current_user.role == "User" and ticket.created_by != current_user.username:
        raise HTTPException(status_code=403, detail="You do not have permission to access this attachment")

    if not ticket.attachment:
        raise HTTPException(status_code=404, detail="This ticket has no attachment")

    target = get_attachment_download_target(ticket.attachment)
    if not target:
        raise HTTPException(status_code=404, detail="Attachment file not found")

    if target["type"] == "s3_presigned":
        if not redirect:
            return {"download_url": target["url"], "filename": target["filename"], "expires_in": 900}
        # Redirect client directly to the secure 15-minute S3 pre-signed URL
        return RedirectResponse(url=target["url"], status_code=307)
    elif target["type"] == "local_file":
        return FileResponse(target["path"], filename=target["filename"])
    else:
        raise HTTPException(status_code=404, detail="Attachment cannot be accessed")

@app.patch("/api/tickets/{ticket_id}/status")
def update_status(
    ticket_id: int,
    payload: StatusUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role == "User":
        raise HTTPException(status_code=403, detail="Users cannot change ticket status")
    if payload.status not in VALID_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")

    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    if current_user.role != "Admin" and ticket.assigned_to != current_user.username:
        raise HTTPException(status_code=403, detail="Engineers can only update tickets assigned to them")

    old_status = ticket.status
    ticket.status = payload.status
    log_activity(db, ticket.id, current_user.username, f"Changed status from '{old_status}' to '{payload.status}'")
    db.commit()
    db.refresh(ticket)
    return ticket

@app.patch("/api/tickets/{ticket_id}/assign")
def assign_ticket(
    ticket_id: int,
    payload: AssignRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role != "Admin":
        raise HTTPException(status_code=403, detail="Only Admins can assign tickets")
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    assignee = payload.assigned_to or None
    ticket.assigned_to = assignee
    action_text = f"Assigned ticket to '{assignee}'" if assignee else "Unassigned ticket"
    log_activity(db, ticket.id, current_user.username, action_text)
    db.commit()
    db.refresh(ticket)
    return ticket

@app.delete("/api/tickets/{ticket_id}")
def delete_ticket(ticket_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.role != "Admin":
        raise HTTPException(status_code=403, detail="Only Admins can delete tickets")
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    db.delete(ticket)
    db.commit()
    return {"message": "Ticket deleted"}

@app.get("/uploads/{filename}")
def get_uploaded_file(
    filename: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Legacy/direct local file access protected with authentication and authorization.
    Requires valid login and enforces RBAC on the associated ticket.
    """
    safe_name = os.path.basename(filename)
    resolved_path = Path(os.path.join(UPLOAD_DIR, safe_name)).resolve()
    resolved_upload_dir = Path(UPLOAD_DIR).resolve()

    if not resolved_path.is_relative_to(resolved_upload_dir) or not resolved_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    # Enforce RBAC: Regular Users can only download files attached to tickets they created
    ticket = db.query(Ticket).filter(Ticket.attachment.like(f"%{safe_name}")).first()
    if ticket and current_user.role == "User" and ticket.created_by != current_user.username:
        raise HTTPException(status_code=403, detail="You do not have permission to access this attachment")
    elif not ticket and current_user.role == "User":
        raise HTTPException(status_code=403, detail="You do not have permission to access this attachment")

    return FileResponse(str(resolved_path), filename=safe_name)
