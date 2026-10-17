from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models, schemas


class NotFoundError(Exception):
    pass


class DuplicatePhoneError(Exception):
    """Raised when creating a patient whose phone_number already matches an
    existing, non-deleted record. Carries the existing patient so the caller
    (REST API or voice tool handler) can surface it."""

    def __init__(self, patient: models.Patient):
        self.patient = patient
        super().__init__(f"Patient with phone number {patient.phone_number} already exists")


def get_patient(db: Session, patient_id: str) -> Optional[models.Patient]:
    stmt = select(models.Patient).where(
        models.Patient.id == patient_id, models.Patient.deleted_at.is_(None)
    )
    return db.execute(stmt).scalar_one_or_none()


def get_patient_by_phone(db: Session, phone_number: str) -> Optional[models.Patient]:
    stmt = select(models.Patient).where(
        models.Patient.phone_number == phone_number, models.Patient.deleted_at.is_(None)
    )
    return db.execute(stmt).scalar_one_or_none()


def list_patients(
    db: Session,
    last_name: Optional[str] = None,
    date_of_birth: Optional[str] = None,
    phone_number: Optional[str] = None,
) -> list[models.Patient]:
    stmt = select(models.Patient).where(models.Patient.deleted_at.is_(None))
    if last_name:
        stmt = stmt.where(models.Patient.last_name.ilike(last_name))
    if date_of_birth:
        stmt = stmt.where(models.Patient.date_of_birth == date_of_birth)
    if phone_number:
        stmt = stmt.where(models.Patient.phone_number == phone_number)
    stmt = stmt.order_by(models.Patient.created_at.desc())
    return list(db.execute(stmt).scalars().all())


def create_patient(db: Session, patient_in: schemas.PatientCreate) -> models.Patient:
    existing = get_patient_by_phone(db, patient_in.phone_number)
    if existing:
        raise DuplicatePhoneError(existing)

    patient = models.Patient(**patient_in.model_dump())
    db.add(patient)
    db.commit()
    db.refresh(patient)
    return patient


def update_patient(db: Session, patient_id: str, patient_in: schemas.PatientUpdate) -> models.Patient:
    patient = get_patient(db, patient_id)
    if patient is None:
        raise NotFoundError(f"No patient found with id {patient_id}")

    updates = patient_in.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(patient, field, value)

    db.add(patient)
    db.commit()
    db.refresh(patient)
    return patient


def soft_delete_patient(db: Session, patient_id: str) -> models.Patient:
    patient = get_patient(db, patient_id)
    if patient is None:
        raise NotFoundError(f"No patient found with id {patient_id}")
    patient.deleted_at = datetime.now(timezone.utc)
    db.add(patient)
    db.commit()
    db.refresh(patient)
    return patient
