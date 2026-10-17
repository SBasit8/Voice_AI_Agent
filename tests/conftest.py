import os

# Must be set before `app.database` / `app.config` are imported anywhere, so
# the app's own lifespan (which creates tables + seeds via the *real*
# engine, independent of the get_db dependency override below) touches a
# throwaway file instead of the project's actual patients.db.
os.environ["DATABASE_URL"] = "sqlite:///./.pytest_patients.db"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app


@pytest.fixture()
def client():
    """Fresh in-memory SQLite DB per test, isolated from any real .env /
    patients.db -- no startup seeding here, each test sets up exactly the
    rows it needs."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="session", autouse=True)
def _cleanup_throwaway_db():
    yield
    try:
        os.remove("./.pytest_patients.db")
    except FileNotFoundError:
        pass


def make_patient_payload(**overrides):
    payload = {
        "first_name": "Jane",
        "last_name": "Doe",
        "date_of_birth": "1990-05-14",
        "sex": "Female",
        "phone_number": "555-123-4567",
        "address_line_1": "123 Main St",
        "city": "Springfield",
        "state": "il",
        "zip_code": "62704",
    }
    payload.update(overrides)
    return payload
