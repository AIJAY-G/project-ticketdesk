from datetime import datetime, timezone
from sqlalchemy import Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship, Mapped, mapped_column
from database import Base


def get_utc_now() -> datetime:
    """Returns a timezone-naive UTC datetime compatible with existing database columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    password: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[str] = mapped_column(String(50), nullable=False, default="Support Engineer")  # "Admin" or "Support Engineer"


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(String(1000), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False, default="Software")
    priority: Mapped[str] = mapped_column(String(50), default="Medium")
    status: Mapped[str] = mapped_column(String(50), default="Open")
    attachment: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_by: Mapped[str] = mapped_column(String(100), nullable=False, default="admin")
    assigned_to: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=get_utc_now)

    activities = relationship("TicketActivity", back_populates="ticket", cascade="all, delete-orphan")


class TicketActivity(Base):
    __tablename__ = "ticket_activities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    ticket_id: Mapped[int] = mapped_column(Integer, ForeignKey("tickets.id"), nullable=False)
    actor: Mapped[str] = mapped_column(String(100), nullable=False)
    action: Mapped[str] = mapped_column(String(300), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=get_utc_now)

    ticket = relationship("Ticket", back_populates="activities")