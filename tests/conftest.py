"""Shared pytest fixtures."""

import pytest
from sqlalchemy.orm import Session

from app.db.session import engine, SessionLocal


@pytest.fixture
def db_session() -> Session:
    """Provide a transactional DB session that rolls back after each test."""
    connection = engine.connect()
    transaction = connection.begin()
    session = SessionLocal(bind=connection)

    yield session

    session.close()
    transaction.rollback()
    connection.close()
