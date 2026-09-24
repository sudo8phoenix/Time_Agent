from collections.abc import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as DBSession, sessionmaker
from ..settings import get_settings

engine = create_engine(get_settings().database_url, pool_pre_ping=True)
session_factory = sessionmaker(bind=engine, expire_on_commit=False, class_=DBSession)

def get_session() -> Generator[DBSession, None, None]:
    db = session_factory()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
