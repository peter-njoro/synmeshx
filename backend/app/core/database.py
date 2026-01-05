from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from app.core.config import settings

# --- SQLAlchemy setup ---

DATABASE_URL = (
    f"postgresql+psycopg2://{settings.postgres_user}:{settings.postgres_password}"
    f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
)
engine = create_engine(DATABASE_URL, future=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
