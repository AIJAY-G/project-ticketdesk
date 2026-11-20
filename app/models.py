from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    password = Column(String(200), nullable=False)
    role = Column(String(50), nullable=False, default="Support Engineer")  # "Admin" or "Support Engineer"

class Ticket(Base):
    __tablename__ = "tickets"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False)
    description = Column(String(1000), nullable=False)
    category = Column(String(100), nullable=False, default="Software")
    priority = Column(String(50), default="Medium")
    status = Column(String(50), default="Open")
    attachment = Column(String(300), nullable=True)
    created_by = Column(String(100), nullable=False, default="admin")
    assigned_to = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    activities = relationship("TicketActivity", back_populates="ticket", cascade="all, delete-orphan")

class TicketActivity(Base):
    __tablename__ = "ticket_activities"

    id = Column(Integer, primary_key=True, index=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id"), nullable=False)
    actor = Column(String(100), nullable=False)
    action = Column(String(300), nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)

    ticket = relationship("Ticket", back_populates="activities")