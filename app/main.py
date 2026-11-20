import os
from datetime import datetime, timedelta
from pathlib import Path
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, Header
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy.orm import Session
from database import Base, engine, get_db, SessionLocal
from models import User, Ticket, TicketActivity
from storage import save_attachment, get_attachment_download_target, UPLOAD_DIR

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Project TicketDesk")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

VALID_STATUSES = ["Open", "In Progress", "Resolved", "Closed"]
VALID_CATEGORIES = ["Hardware", "Software", "Network", "Email", "Account Access"]
VALID_ROLES = ["Admin", "Support Engineer", "User"]

# Seed default accounts if database is empty
def seed_users():
    db = SessionLocal()
    try:
        if db.query(User).count() == 0:
            admin_user = os.getenv("ADMIN_USERNAME", "admin")
            admin_pass = os.getenv("ADMIN_PASSWORD", "admin123")
            db.add_all([
                User(username=admin_user, password=admin_pass, role="Admin"),
                User(username="eng1", password="eng123", role="Support Engineer"),
                User(username="eng2", password="eng123", role="Support Engineer"),
                User(username="user1", password="user123", role="User"),
            ])
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

def get_current_user(x_username: str = Header(None), db: Session = Depends(get_db)) -> User:
    if not x_username:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user = db.query(User).filter(User.username == x_username).first()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid user")
    return user

def log_activity(db: Session, ticket_id: int, actor: str, action: str):
    db.add(TicketActivity(ticket_id=ticket_id, actor=actor, action=action))

@app.get("/")
def serve_frontend():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))

@app.post("/api/login")
def login(creds: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == creds.username, User.password == creds.password).first()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return {"message": "Login successful", "username": user.username, "role": user.role}

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

    # Always force role="User" on self-signup so users cannot make themselves Admin
    new_user = User(username=username, password=password, role="User")
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return {
        "message": "Account created successfully",
        "username": new_user.username,
        "role": new_user.role,
    }

# --- User Management ---
@app.get("/api/users")
def list_users(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    users = db.query(User).all()
    return [{"id": u.id, "username": u.username, "role": u.role} for u in users]

@app.post("/api/users")
def create_user(payload: CreateUserRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.role != "Admin":
        raise HTTPException(status_code=403, detail="Only Admins can create users")
    if payload.role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail="Invalid role")
    if db.query(User).filter(User.username == payload.username).first():
        raise HTTPException(status_code=400, detail="Username already exists")
    user = User(username=payload.username.strip(), password=payload.password, role=payload.role)
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

    now = datetime.utcnow()
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
def get_uploaded_file(filename: str):
    """Legacy/direct local file access with path traversal protection."""
    safe_name = os.path.basename(filename)
    resolved_path = Path(os.path.join(UPLOAD_DIR, safe_name)).resolve()
    resolved_upload_dir = Path(UPLOAD_DIR).resolve()

    if not resolved_path.is_relative_to(resolved_upload_dir) or not resolved_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(str(resolved_path), filename=safe_name)
