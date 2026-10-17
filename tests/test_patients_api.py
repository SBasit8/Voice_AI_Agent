from .conftest import make_patient_payload


def test_create_patient_success(client):
    resp = client.post("/patients", json=make_patient_payload())
    assert resp.status_code == 201
    body = resp.json()
    assert body["error"] is None
    data = body["data"]
    assert data["first_name"] == "Jane"
    assert data["state"] == "IL"  # normalized to uppercase
    assert data["phone_number"] == "5551234567"  # normalized, no punctuation
    assert data["preferred_language"] == "English"  # default applied
    assert "patient_id" in data


def test_create_patient_envelope_on_success_has_null_error(client):
    resp = client.post("/patients", json=make_patient_payload(phone_number="555-000-1111"))
    assert resp.json()["error"] is None


def test_get_patient_by_id(client):
    created = client.post("/patients", json=make_patient_payload()).json()["data"]
    resp = client.get(f"/patients/{created['patient_id']}")
    assert resp.status_code == 200
    assert resp.json()["data"]["patient_id"] == created["patient_id"]


def test_get_patient_not_found(client):
    resp = client.get("/patients/does-not-exist")
    assert resp.status_code == 404
    body = resp.json()
    assert body["data"] is None
    assert body["error"]["message"] == "Patient not found"


def test_list_patients_filters_by_last_name(client):
    client.post("/patients", json=make_patient_payload(last_name="Davis", phone_number="5550001111"))
    client.post("/patients", json=make_patient_payload(last_name="Garcia", phone_number="5550002222"))

    resp = client.get("/patients", params={"last_name": "Davis"})
    data = resp.json()["data"]
    assert len(data) == 1
    assert data[0]["last_name"] == "Davis"


def test_list_patients_filters_by_phone_number(client):
    client.post("/patients", json=make_patient_payload(phone_number="5559998888"))
    resp = client.get("/patients", params={"phone_number": "(555) 999-8888"})
    data = resp.json()["data"]
    assert len(data) == 1
    assert data[0]["phone_number"] == "5559998888"


def test_update_patient_partial(client):
    created = client.post("/patients", json=make_patient_payload()).json()["data"]
    resp = client.put(f"/patients/{created['patient_id']}", json={"city": "Chicago"})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["city"] == "Chicago"
    assert data["first_name"] == "Jane"  # untouched fields preserved


def test_update_patient_not_found(client):
    resp = client.put("/patients/does-not-exist", json={"city": "Chicago"})
    assert resp.status_code == 404


def test_soft_delete_patient(client):
    created = client.post("/patients", json=make_patient_payload()).json()["data"]
    patient_id = created["patient_id"]

    resp = client.delete(f"/patients/{patient_id}")
    assert resp.status_code == 200
    assert resp.json()["data"]["deleted_at"] is not None

    # Soft-deleted patients disappear from reads...
    assert client.get(f"/patients/{patient_id}").status_code == 404
    assert client.get("/patients").json()["data"] == []


def test_soft_delete_not_found(client):
    resp = client.delete("/patients/does-not-exist")
    assert resp.status_code == 404


# --- Validation rules ---------------------------------------------------


def test_reject_future_date_of_birth(client):
    resp = client.post("/patients", json=make_patient_payload(date_of_birth="2999-01-01"))
    assert resp.status_code == 422
    fields = [d["field"] for d in resp.json()["error"]["details"]]
    assert "date_of_birth" in fields


def test_reject_invalid_phone_number(client):
    resp = client.post("/patients", json=make_patient_payload(phone_number="123"))
    assert resp.status_code == 422
    fields = [d["field"] for d in resp.json()["error"]["details"]]
    assert "phone_number" in fields


def test_reject_invalid_state(client):
    resp = client.post("/patients", json=make_patient_payload(state="ZZ"))
    assert resp.status_code == 422


def test_reject_invalid_zip(client):
    resp = client.post("/patients", json=make_patient_payload(zip_code="abcde"))
    assert resp.status_code == 422


def test_reject_name_with_digits(client):
    resp = client.post("/patients", json=make_patient_payload(first_name="J4ne"))
    assert resp.status_code == 422


def test_reject_invalid_sex_enum(client):
    resp = client.post("/patients", json=make_patient_payload(sex="Unknown"))
    assert resp.status_code == 422


def test_accepts_optional_fields(client):
    resp = client.post(
        "/patients",
        json=make_patient_payload(
            phone_number="5553334444",
            email="jane@example.com",
            insurance_provider="Aetna",
            insurance_member_id="AET999",
            emergency_contact_name="John Doe",
            emergency_contact_phone="555-222-3333",
        ),
    )
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["insurance_provider"] == "Aetna"
    assert data["emergency_contact_phone"] == "5552223333"


# --- Duplicate detection -------------------------------------------------


def test_duplicate_phone_number_rejected(client):
    client.post("/patients", json=make_patient_payload(phone_number="5551112222"))
    resp = client.post(
        "/patients",
        json=make_patient_payload(first_name="Mariana", last_name="Gomez", phone_number="5551112222"),
    )
    assert resp.status_code == 400
    assert "existing_patient_id" in resp.json()["error"]["details"]


# --- Vapi tool-call webhook ----------------------------------------------


def _tool_call(client, name, arguments, call_id="call_1"):
    return client.post(
        "/vapi/webhook",
        json={
            "message": {
                "type": "tool-calls",
                "toolCallList": [
                    {"id": call_id, "type": "function", "function": {"name": name, "arguments": arguments}}
                ],
            }
        },
    )


def test_vapi_create_patient_tool_call(client):
    resp = _tool_call(client, "create_patient", make_patient_payload(phone_number="5556667777"))
    assert resp.status_code == 200
    result = resp.json()["results"][0]
    assert result["toolCallId"] == "call_1"
    import json

    payload = json.loads(result["result"])
    assert payload["success"] is True
    assert "patient_id" in payload


def test_vapi_create_patient_tool_call_validation_error_targets_field(client):
    resp = _tool_call(
        client, "create_patient", make_patient_payload(phone_number="5556667777", date_of_birth="not-a-date")
    )
    import json

    payload = json.loads(resp.json()["results"][0]["result"])
    assert payload["success"] is False
    assert payload["field"] == "date_of_birth"


def test_vapi_check_existing_patient_found(client):
    client.post("/patients", json=make_patient_payload(phone_number="5558887777"))
    resp = _tool_call(client, "check_existing_patient", {"phone_number": "555-888-7777"})
    import json

    payload = json.loads(resp.json()["results"][0]["result"])
    assert payload["found"] is True


def test_vapi_unknown_tool_name_handled_gracefully(client):
    resp = _tool_call(client, "delete_everything", {})
    import json

    payload = json.loads(resp.json()["results"][0]["result"])
    assert payload["success"] is False


def test_vapi_end_of_call_report_stores_transcript(client):
    client.post("/patients", json=make_patient_payload(phone_number="5551239999"))
    resp = client.post(
        "/vapi/webhook",
        json={
            "message": {
                "type": "end-of-call-report",
                "call": {"id": "call-xyz", "customer": {"number": "+15551239999"}},
                "transcript": "...",
                "summary": "Registered Jane Doe.",
                "endedReason": "customer-ended-call",
            }
        },
    )
    assert resp.status_code == 200
    assert resp.json() == {"received": True}
