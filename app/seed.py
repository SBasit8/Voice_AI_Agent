import logging
from datetime import date

from sqlalchemy.orm import Session

from . import models

logger = logging.getLogger("app.seed")

_SEED_PATIENTS = [
    dict(
        first_name="Jane",
        last_name="Doe",
        date_of_birth=date(1990, 5, 14),
        sex="Female",
        phone_number="5551234567",
        email="jane.doe@example.com",
        address_line_1="123 Main St",
        address_line_2="Apt 4B",
        city="Springfield",
        state="IL",
        zip_code="62704",
        insurance_provider="Blue Cross Blue Shield",
        insurance_member_id="BCBS123456",
        preferred_language="English",
        emergency_contact_name="John Doe",
        emergency_contact_phone="5559876543",
    ),
    dict(
        first_name="Carlos",
        last_name="Mendoza",
        date_of_birth=date(1978, 11, 2),
        sex="Male",
        phone_number="5552223333",
        email=None,
        address_line_1="48 Oak Avenue",
        address_line_2=None,
        city="Austin",
        state="TX",
        zip_code="73301",
        insurance_provider=None,
        insurance_member_id=None,
        preferred_language="Spanish",
        emergency_contact_name=None,
        emergency_contact_phone=None,
    ),
]


def seed_if_empty(db: Session) -> None:
    """Demo-only fake data (per the assessment's FAQ: do not store real
    patient data). No-op if the table already has rows, so this is safe to
    call on every startup."""
    if db.query(models.Patient).first() is not None:
        return

    for data in _SEED_PATIENTS:
        db.add(models.Patient(**data))
    db.commit()
    logger.info("seed_data_inserted", extra={"count": len(_SEED_PATIENTS)})
