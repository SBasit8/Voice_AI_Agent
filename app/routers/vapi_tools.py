"""Webhook endpoint the Vapi assistant talks to during a live phone call.

Vapi sends every "server message" for an assistant to a single configured
URL (`serverUrl` in assistant_config), differentiated by `message.type`.
Two message types matter for this build:

1. "tool-calls" -- sent synchronously whenever the assistant invokes one of
   the functions declared in vapi/tools_schema.json (check_existing_patient /
   create_patient / update_patient). We must respond with a `results` array
   matching each `toolCallId`; Vapi speaks/reasons over whatever we put in
   `result`. This is also where server-side validation is actually enforced
   -- the LLM is asked to pre-validate in its system prompt, but this
   endpoint is the real authority, exactly like the REST API is for direct
   HTTP clients.

2. "end-of-call-report" -- sent once after the call hangs up. Used to
   persist a transcript/summary linked to the patient (bonus: call
   recording/transcript), keyed by caller phone number.

Any other message type (status-update, transcript, speech-update, ...) is
acknowledged and ignored.
"""

import json
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import ValidationError
from sqlalchemy.orm import Session

from .. import crud, models, schemas
from ..config import settings
from ..database import get_db
from ..validators import normalize_phone

logger = logging.getLogger("app.vapi")

router = APIRouter(prefix="/vapi", tags=["vapi"])


def _check_secret(x_vapi_secret: str | None):
    if settings.vapi_webhook_secret and x_vapi_secret != settings.vapi_webhook_secret:
        raise HTTPException(status_code=401, detail="invalid webhook secret")


def _format_validation_error(exc: ValidationError) -> dict:
    first = exc.errors()[0]
    field = first["loc"][-1] if first["loc"] else "unknown"
    return {"success": False, "field": str(field), "error": first["msg"]}


def tool_check_existing_patient(args: dict, db: Session) -> dict:
    phone = args.get("phone_number", "")
    try:
        normalized = normalize_phone(phone)
    except ValueError as exc:
        return {"success": False, "field": "phone_number", "error": str(exc)}

    patient = crud.get_patient_by_phone(db, normalized)
    if patient:
        return {
            "success": True,
            "found": True,
            "patient_id": patient.id,
            "first_name": patient.first_name,
            "last_name": patient.last_name,
        }
    return {"success": True, "found": False}


def tool_create_patient(args: dict, db: Session) -> dict:
    try:
        patient_in = schemas.PatientCreate(**args)
    except ValidationError as exc:
        return _format_validation_error(exc)

    try:
        patient = crud.create_patient(db, patient_in)
    except crud.DuplicatePhoneError as exc:
        return {
            "success": False,
            "duplicate": True,
            "patient_id": exc.patient.id,
            "first_name": exc.patient.first_name,
            "last_name": exc.patient.last_name,
            "error": "A patient with this phone number already exists.",
        }

    logger.info(
        "voice_patient_created",
        extra={"patient_id": patient.id, "payload": patient_in.model_dump(mode="json")},
    )
    return {
        "success": True,
        "patient_id": patient.id,
        "message": f"Patient {patient.first_name} {patient.last_name} created successfully.",
    }


def tool_update_patient(args: dict, db: Session) -> dict:
    args = dict(args)
    patient_id = args.pop("patient_id", None)
    if not patient_id:
        return {"success": False, "error": "patient_id is required to update a record."}

    try:
        patient_in = schemas.PatientUpdate(**args)
    except ValidationError as exc:
        return _format_validation_error(exc)

    try:
        patient = crud.update_patient(db, patient_id, patient_in)
    except crud.NotFoundError:
        return {"success": False, "error": "No patient found with that ID."}

    logger.info(
        "voice_patient_updated",
        extra={
            "patient_id": patient.id,
            "payload": patient_in.model_dump(mode="json", exclude_unset=True),
        },
    )
    return {"success": True, "patient_id": patient.id, "message": "Patient record updated successfully."}


TOOL_HANDLERS = {
    "check_existing_patient": tool_check_existing_patient,
    "create_patient": tool_create_patient,
    "update_patient": tool_update_patient,
}


def _handle_tool_calls(message: dict, db: Session) -> dict:
    tool_calls = message.get("toolCallList") or message.get("toolCalls") or []

    results = []
    for tc in tool_calls:
        call_id = tc.get("id")
        function = tc.get("function", {})
        name = function.get("name")
        raw_args = function.get("arguments")

        if isinstance(raw_args, str):
            try:
                args = json.loads(raw_args) if raw_args else {}
            except json.JSONDecodeError:
                args = {}
        else:
            args = raw_args or {}

        handler = TOOL_HANDLERS.get(name)
        logger.info("vapi_tool_call_received", extra={"tool": name, "tool_args": args})

        if handler is None:
            result = {"success": False, "error": f"Unknown tool '{name}'"}
        else:
            try:
                result = handler(args, db)
            except Exception:
                logger.exception("vapi_tool_call_failed", extra={"tool": name})
                result = {
                    "success": False,
                    "error": "Internal error while saving the record. Please try again.",
                }

        results.append({"toolCallId": call_id, "result": json.dumps(result)})

    return {"results": results}


def _handle_end_of_call_report(message: dict, db: Session) -> dict:
    call = message.get("call", {}) or {}
    call_id = call.get("id") or "unknown"
    customer = call.get("customer", {}) or {}
    phone_number = customer.get("number")

    artifact = message.get("artifact", {}) or {}
    transcript = message.get("transcript") or artifact.get("transcript")
    summary = message.get("summary") or artifact.get("summary")
    ended_reason = message.get("endedReason")

    patient_id = None
    if phone_number:
        try:
            normalized = normalize_phone(phone_number)
            patient = crud.get_patient_by_phone(db, normalized)
            if patient:
                patient_id = patient.id
        except ValueError:
            pass

    existing = db.query(models.CallLog).filter(models.CallLog.call_id == call_id).first()
    if existing is None:
        db.add(
            models.CallLog(
                call_id=call_id,
                patient_id=patient_id,
                phone_number=phone_number,
                transcript=transcript,
                summary=summary,
                ended_reason=ended_reason,
            )
        )
        db.commit()

    logger.info(
        "call_ended",
        extra={"call_id": call_id, "patient_id": patient_id, "ended_reason": ended_reason},
    )
    return {"received": True}


@router.post("/webhook")
async def handle_vapi_webhook(
    request: Request,
    db: Session = Depends(get_db),
    x_vapi_secret: str | None = Header(default=None),
):
    """Single entry point for every Vapi server message. Configure this URL
    (not /tool-calls or /events) as the assistant's serverUrl -- Vapi does
    not support registering more than one webhook URL per assistant, so all
    message types arrive here and are dispatched by `message.type`."""
    _check_secret(x_vapi_secret)

    body = await request.json()
    message = body.get("message", {})
    msg_type = message.get("type")

    if msg_type == "tool-calls":
        return _handle_tool_calls(message, db)

    if msg_type == "end-of-call-report":
        return _handle_end_of_call_report(message, db)

    logger.info("vapi_event_ignored", extra={"type": msg_type})
    return {"received": True}
