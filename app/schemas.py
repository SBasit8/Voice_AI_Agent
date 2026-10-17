from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from .validators import normalize_phone, parse_dob, validate_name, validate_state, validate_zip

SexEnum = Literal["Male", "Female", "Other", "Decline to Answer"]


class PatientCreate(BaseModel):
    """Full set of fields for a new registration. Required fields match the
    assessment's 'standard minimum demographic dataset' table exactly."""

    first_name: str
    last_name: str
    date_of_birth: date
    sex: SexEnum
    phone_number: str
    email: Optional[EmailStr] = None
    address_line_1: str
    address_line_2: Optional[str] = None
    city: str
    state: str
    zip_code: str
    insurance_provider: Optional[str] = None
    insurance_member_id: Optional[str] = None
    preferred_language: Optional[str] = "English"
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None

    @field_validator("first_name")
    @classmethod
    def _first_name(cls, v: str) -> str:
        return validate_name(v, "first_name")

    @field_validator("last_name")
    @classmethod
    def _last_name(cls, v: str) -> str:
        return validate_name(v, "last_name")

    @field_validator("date_of_birth", mode="before")
    @classmethod
    def _dob(cls, v):
        return parse_dob(v)

    @field_validator("phone_number")
    @classmethod
    def _phone(cls, v: str) -> str:
        return normalize_phone(v)

    @field_validator("emergency_contact_phone")
    @classmethod
    def _ec_phone(cls, v):
        if v is None or v == "":
            return None
        return normalize_phone(v)

    @field_validator("address_line_1")
    @classmethod
    def _addr1(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("address_line_1 is required")
        return v

    @field_validator("city")
    @classmethod
    def _city(cls, v: str) -> str:
        v = (v or "").strip()
        if not (1 <= len(v) <= 100):
            raise ValueError("city must be between 1 and 100 characters")
        return v

    @field_validator("state")
    @classmethod
    def _state(cls, v: str) -> str:
        return validate_state(v)

    @field_validator("zip_code")
    @classmethod
    def _zip(cls, v: str) -> str:
        return validate_zip(v)

    @field_validator("preferred_language")
    @classmethod
    def _lang(cls, v):
        if not v or not v.strip():
            return "English"
        return v.strip()


class PatientUpdate(BaseModel):
    """Same validation rules as PatientCreate, but every field is optional so
    PUT /patients/:id can do partial updates. `None` means "not supplied",
    not "clear this field"."""

    first_name: Optional[str] = None
    last_name: Optional[str] = None
    date_of_birth: Optional[date] = None
    sex: Optional[SexEnum] = None
    phone_number: Optional[str] = None
    email: Optional[EmailStr] = None
    address_line_1: Optional[str] = None
    address_line_2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None
    insurance_provider: Optional[str] = None
    insurance_member_id: Optional[str] = None
    preferred_language: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None

    @field_validator("first_name")
    @classmethod
    def _first_name(cls, v):
        return v if v is None else validate_name(v, "first_name")

    @field_validator("last_name")
    @classmethod
    def _last_name(cls, v):
        return v if v is None else validate_name(v, "last_name")

    @field_validator("date_of_birth", mode="before")
    @classmethod
    def _dob(cls, v):
        return v if v is None else parse_dob(v)

    @field_validator("phone_number")
    @classmethod
    def _phone(cls, v):
        return v if v is None else normalize_phone(v)

    @field_validator("emergency_contact_phone")
    @classmethod
    def _ec_phone(cls, v):
        return v if v in (None, "") else normalize_phone(v)

    @field_validator("address_line_1")
    @classmethod
    def _addr1(cls, v):
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError("address_line_1 cannot be blank")
        return v

    @field_validator("city")
    @classmethod
    def _city(cls, v):
        if v is None:
            return v
        v = v.strip()
        if not (1 <= len(v) <= 100):
            raise ValueError("city must be between 1 and 100 characters")
        return v

    @field_validator("state")
    @classmethod
    def _state(cls, v):
        return v if v is None else validate_state(v)

    @field_validator("zip_code")
    @classmethod
    def _zip(cls, v):
        return v if v is None else validate_zip(v)


class PatientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    patient_id: str = Field(validation_alias="id")
    first_name: str
    last_name: str
    date_of_birth: date
    sex: str
    phone_number: str
    email: Optional[str] = None
    address_line_1: str
    address_line_2: Optional[str] = None
    city: str
    state: str
    zip_code: str
    insurance_provider: Optional[str] = None
    insurance_member_id: Optional[str] = None
    preferred_language: str
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None
