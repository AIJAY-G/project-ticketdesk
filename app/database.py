import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
default_db_path = os.path.join(BASE_DIR, "ticketdesk.db")

raw_database_url = os.getenv("DATABASE_URL")

# Fall back to local SQLite if DATABASE_URL is unset, empty, or whitespace
if not raw_database_url or not raw_database_url.strip():
    DATABASE_URL = f"sqlite:///{default_db_path}"
else:
    DATABASE_URL = raw_database_url.strip()

# Normalize PostgreSQL connection URLs for SQLAlchemy 2.0 with psycopg2 driver
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg2://", 1)
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1)

# Configure database engine based on dialect
if DATABASE_URL.startswith("sqlite"):
    # SQLite requires check_same_thread=False for multi-threaded FastAPI access
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
    )
else:
    # PostgreSQL configuration optimized for Amazon RDS POC
    # Enforce SSL encryption for RDS connections unless explicitly disabled
    connect_args = {}
    if "sslmode" not in DATABASE_URL.lower():
        connect_args["sslmode"] = "require"

    engine = create_engine(
        DATABASE_URL,
        connect_args=connect_args,
        pool_pre_ping=True,   # Tests connection liveness before checkout to prevent stale connection errors
        pool_size=5,          # Baseline pool of persistent connections for the POC
        max_overflow=10,      # Additional temporary connections during load spikes
        pool_recycle=1800,    # Recycle connections after 30 minutes to avoid firewall/RDS idle drops
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
