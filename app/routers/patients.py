import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from .. import crud, schemas
from ..database import get_db
from ..errors import AppError, envelope
from ..validators import normalize_phone, parse_dob

logger = logging.getLogger("app.api.patients")

router = APIRouter(prefix="/patients", tags=["patients"])


@router.get("", summary="List patients, optionally filtered")
def list_patients(
    last_name: Optional[str] = Query(None),
    date_of_birth: Optional[str] = Query(None, description="MM/DD/YYYY or YYYY-MM-DD"),
    phone_number: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    dob_filter = None
    if date_of_birth:
        try:
            dob_filter = parse_dob(date_of_birth)
        except ValueError as exc:
            raise AppError(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))

    phone_filter = None
    if phone_number:
        try:
            phone_filter = normalize_phone(phone_number)
        except ValueError as exc:
            raise AppError(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))

    patients = crud.list_patients(
        db, last_name=last_name, date_of_birth=dob_filter, phone_number=phone_filter
    )
    data = [schemas.PatientOut.model_validate(p).model_dump(mode="json") for p in patients]
    return envelope(data=data)


@router.get("/{patient_id}", summary="Retrieve a single patient by patient_id")
def get_patient(patient_id: str, db: Session = Depends(get_db)):
    patient = crud.get_patient(db, patient_id)
    if patient is None:
        raise AppError(status.HTTP_404_NOT_FOUND, "Patient not found")
    return envelope(data=schemas.PatientOut.model_validate(patient).model_dump(mode="json"))


@router.post("", status_code=status.HTTP_201_CREATED, summary="Create a new patient")
def create_patient(patient_in: schemas.PatientCreate, db: Session = Depends(get_db)):
    try:
        patient = crud.create_patient(db, patient_in)
    except crud.DuplicatePhoneError as exc:
        raise AppError(
            status.HTTP_400_BAD_REQUEST,
            "A patient with this phone number already exists.",
            details={"existing_patient_id": exc.patient.id},
        )

    logger.info(
        "patient_created",
        extra={"patient_id": patient.id, "payload": patient_in.model_dump(mode="json")},
    )
    return envelope(data=schemas.PatientOut.model_validate(patient).model_dump(mode="json"))


@router.put("/{patient_id}", summary="Update an existing patient (partial updates allowed)")
def update_patient(patient_id: str, patient_in: schemas.PatientUpdate, db: Session = Depends(get_db)):
    try:
        patient = crud.update_patient(db, patient_id, patient_in)
    except crud.NotFoundError:
        raise AppError(status.HTTP_404_NOT_FOUND, "Patient not found")

    logger.info(
        "patient_updated",
        extra={"patient_id": patient.id, "payload": patient_in.model_dump(mode="json", exclude_unset=True)},
    )
    return envelope(data=schemas.PatientOut.model_validate(patient).model_dump(mode="json"))


@router.delete("/{patient_id}", summary="Soft-delete a patient (sets deleted_at)")
def delete_patient(patient_id: str, db: Session = Depends(get_db)):
    try:
        patient = crud.soft_delete_patient(db, patient_id)
    except crud.NotFoundError:
        raise AppError(status.HTTP_404_NOT_FOUND, "Patient not found")

    logger.info("patient_deleted", extra={"patient_id": patient.id})
    return envelope(data={"patient_id": patient.id, "deleted_at": patient.deleted_at.isoformat()})
