# Voice AI Patient Registration Agent

A voice-based AI agent that answers a real phone number, conversationally
registers a new patient (or updates an existing one), persists the record to
a database, and exposes it through a REST API + a small web dashboard.

Built for the "Voice AI Agent — Patient Registration" take-home assessment.

> **Do not store real patient data.** All seed/demo data in this repo is
> fake, per the assessment's own instructions.

---

## Live Demo

| What | Where |
|---|---|
| Phone number | **+1 (209) 819-5381** |
| API base URL | https://voice-ai-patient-registration-7379.onrender.com |
| Dashboard | https://voice-ai-patient-registration-7379.onrender.com/dashboard |
| API docs (Swagger) | https://voice-ai-patient-registration-7379.onrender.com/docs |

Note: the backend runs on Render's free tier, which spins down after periods
of inactivity — the first request after a while may take ~30-50s to respond
while the instance wakes up. The free Postgres instance also expires 30 days
after creation (2026-11-16); if the demo is reviewed after that date, the
database will need to be re-provisioned.

---

## Architecture

```
 Caller (phone)
      │
      ▼
   Vapi  ──────────────  telephony + STT (Deepgram) + TTS + LLM (GPT-4o-mini)
      │  tool-calls / end-of-call-report (HTTPS webhook, JSON)
      ▼
 FastAPI backend  (this repo)
   ├─ app/routers/vapi_tools.py   POST /vapi/webhook   (voice ↔ backend bridge)
   ├─ app/routers/patients.py     REST API  /patients   (human/system clients)
   ├─ app/schemas.py              Pydantic validation (the single source of truth
   │                              for every rule in the assessment's data table)
   ├─ app/crud.py                 DB operations + duplicate-phone detection
   └─ app/models.py               SQLAlchemy ORM (Patient, CallLog)
      │
      ▼
 SQLite (dev) / PostgreSQL (prod, Render)
```

**Why this split:** the voice agent and the REST API are two different
*clients* of the same service layer (`app/crud.py` + `app/schemas.py`) —
neither one re-implements validation or persistence. A phone call and an
`curl -X POST /patients` end up running exactly the same Pydantic validators
and the exact same duplicate-phone check, so "garbage in" is rejected
identically either way. This directly satisfies the assessment's "validate
all inputs server-side (do not rely solely on the voice agent)" requirement
— the voice agent's system prompt does its own light pre-validation for a
better conversational experience, but it is not trusted.

### Why Vapi (vs. building STT/TTS from scratch)

Vapi bundles telephony, speech-to-text (Deepgram), text-to-speech, turn-taking
/ interruption handling, and LLM orchestration behind one webhook contract.
That's exactly the "fastest path to a working system" the assessment calls
out, and it means this repo's own code is 100% focused on the actual
engineering questions being evaluated: conversation design (the system
prompt), data modeling, validation, and API design — not re-deriving
barge-in detection or audio streaming.

### Why FastAPI + SQLAlchemy + Pydantic

- **FastAPI**: async-native, automatic OpenAPI docs (`/docs`), and its
  request-validation model maps directly onto the Pydantic schemas already
  needed for the voice-tool validation — one schema, two entry points.
- **SQLAlchemy ORM**: keeps the data layer database-agnostic. Locally this
  runs on SQLite (zero setup); in production it runs on Postgres with *no
  code changes* — only `DATABASE_URL` differs (see below).
- **Pydantic v2 validators**: centralize every rule from the assessment's
  data-model table (name charset, 10-digit phone, DOB not in the future,
  2-letter state, ZIP/ZIP+4, enum for `sex`) in one place
  (`app/validators.py` + `app/schemas.py`), shared by both the REST API and
  the voice tool-call handler.

### Why SQLite locally but Postgres in production

The assessment explicitly praises "SQLite over Postgres" as a smart,
time-boxed trade-off — and for local development that's exactly right: zero
setup, a single file, instant iteration. But the assessment also has a hard
requirement: *"data must survive server restarts... if we register Jane Doe
on Call 1, she must exist when we query on Call 2."* Render's free web
services have an **ephemeral filesystem** — a SQLite file written there does
not reliably survive a redeploy or restart. Rather than gamble on that
requirement, production uses Render's managed Postgres (also free to start)
via the same `DATABASE_URL` environment variable SQLAlchemy already reads.
Nothing in the application code is Postgres- or SQLite-specific.

---

## Data Model

`app/models.py` implements the exact table from the assessment:

| Field | Required | Enforced by |
|---|---|---|
| `first_name`, `last_name` | Yes | 1–50 chars, letters/hyphens/apostrophes only |
| `date_of_birth` | Yes | valid calendar date, not in the future |
| `sex` | Yes | enum: Male / Female / Other / Decline to Answer |
| `phone_number` | Yes | normalized to a 10-digit U.S. number |
| `email` | No | RFC-valid email |
| `address_line_1` | Yes | non-blank |
| `address_line_2` | No | — |
| `city` | Yes | 1–100 chars |
| `state` | Yes | valid 2-letter U.S. abbreviation |
| `zip_code` | Yes | 5-digit or ZIP+4 |
| `insurance_provider`, `insurance_member_id` | No | — |
| `preferred_language` | No | defaults to "English" |
| `emergency_contact_name`, `emergency_contact_phone` | No | phone normalized if present |
| `patient_id`, `created_at`, `updated_at` | Auto | UUID / UTC timestamps |
| `deleted_at` | Auto | set by soft-delete, never hard-deletes a row |

Per the assessment's conversational note, the voice agent only *asks* for
required fields by default, then offers the optional ones in one line — it
never reads them out as a checklist (see `vapi/system_prompt.md`).

---

## REST API

All responses use the envelope `{ "data": ..., "error": ... }`.

| Method | Path | Notes |
|---|---|---|
| `GET` | `/patients` | optional `?last_name=`, `?date_of_birth=`, `?phone_number=` |
| `GET` | `/patients/{id}` | 404 if missing or soft-deleted |
| `POST` | `/patients` | 201 on success, 400 on duplicate phone, 422 on validation failure |
| `PUT` | `/patients/{id}` | partial update, 404 if missing |
| `DELETE` | `/patients/{id}` | soft-delete (`deleted_at` set, row kept) |

Full interactive docs: `GET /docs` (Swagger UI, auto-generated by FastAPI).

---

## Voice ↔ Backend Integration

Vapi calls a single webhook, `POST /vapi/webhook` (`app/routers/vapi_tools.py`),
for everything — Vapi only supports one `serverUrl` per assistant, so every
server message (tool calls, end-of-call reports, etc.) arrives there and is
dispatched by `message.type`:

- **`tool-calls`** → one of three functions the LLM can invoke:
  - `check_existing_patient(phone_number)` — looks up a caller by phone as
    soon as it's collected. If found, the agent asks whether to update
    instead of creating a duplicate (the assessment's bonus "duplicate
    detection" behavior).
  - `create_patient(...)` — runs through the *exact same* Pydantic
    validation as `POST /patients`. On failure, the response names the
    specific invalid `field` so the agent re-prompts for only that one.
  - `update_patient(patient_id, ...)` — partial update for a returning
    caller.
- **`end-of-call-report`** → persists a transcript/summary to the `CallLog`
  table, linked to the matching patient by phone number (bonus: call
  transcript, visible via `CallLog` — not yet exposed in the dashboard UI;
  see Known Limitations).

The full conversational design — tone, turn structure, how corrections and
interruptions are handled, how validation errors get translated into a
re-prompt, what happens on a tool failure — is documented and commented in
[`vapi/system_prompt.md`](vapi/system_prompt.md). The tool/function JSON
schemas the assistant is given are in
[`vapi/tools_schema.json`](vapi/tools_schema.json).

---

## Observability

Every request is logged as a structured JSON line to stdout
(`app/logging_config.py`) — Render captures stdout directly, so no extra
infrastructure is needed. At minimum, every successful create/update logs
the full collected payload and patient ID:

```json
{"timestamp": "...", "level": "INFO", "logger": "app.vapi", "message": "voice_patient_created", "patient_id": "...", "payload": {...}}
```

---

## Security

- No secrets are hardcoded anywhere in source. `VAPI_API_KEY`,
  `VAPI_WEBHOOK_SECRET`, and `DATABASE_URL` are all read from the
  environment (`.env` locally, Render's env var UI in production).
- The `/vapi/webhook` endpoint checks an `x-vapi-secret` header against
  `VAPI_WEBHOOK_SECRET` when that variable is set, so random internet
  traffic can't pretend to be Vapi and write patient records.
- All input is validated server-side via Pydantic regardless of which
  client (voice agent or direct HTTP) sent it — see "Architecture" above.

---

## Project Layout

```
app/
  main.py              FastAPI app, exception handlers, startup (create tables + seed)
  config.py            Settings from environment variables
  database.py          SQLAlchemy engine/session (SQLite or Postgres via DATABASE_URL)
  models.py            Patient, CallLog ORM models
  schemas.py            PatientCreate / PatientUpdate / PatientOut (validation lives here)
  validators.py        Reusable field validators (name, phone, zip, state, dob)
  crud.py              DB operations incl. duplicate-phone detection, soft delete
  errors.py             AppError + the {data, error} envelope helper
  logging_config.py    Structured stdout logging
  seed.py               Two fake demo patients, inserted only if the table is empty
  routers/
    patients.py         REST API
    vapi_tools.py        Vapi webhook (tool-calls + end-of-call-report)
  static/dashboard.html  Bonus: simple web UI over the REST API
vapi/
  system_prompt.md       The documented conversational design / system prompt
  tools_schema.json      Tool/function JSON schemas given to the assistant
  create_assistant.py    Best-effort script to provision the assistant + number via Vapi's API
tests/
  test_patients_api.py   23 tests: CRUD, validation, duplicates, soft-delete, Vapi tool-calls
```

---

## Setup

### 1. Install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
```

| Variable | Required | Purpose |
|---|---|---|
| `DATABASE_URL` | No (defaults to local SQLite) | `sqlite:///./patients.db` locally, Postgres URL in production |
| `VAPI_API_KEY` | Only for `vapi/create_assistant.py` | Provisions the assistant/number via Vapi's API |
| `VAPI_WEBHOOK_SECRET` | Recommended in production | Verifies incoming Vapi webhook requests |
| `PUBLIC_BASE_URL` | Only for `vapi/create_assistant.py` | Public URL Vapi should call (ngrok URL locally, Render URL in prod) |
| `LOG_LEVEL` | No | defaults to `INFO` |

### 3. Run the server

```bash
uvicorn app.main:app --reload
```

- API: http://localhost:8000
- Dashboard: http://localhost:8000/dashboard
- Swagger docs: http://localhost:8000/docs

On first boot, tables are created automatically and (if the table is empty)
two fake demo patients are seeded.

### 4. Run tests

```bash
pytest tests/ -v
```

23 tests cover: CRUD, every validation rule from the data-model table,
duplicate-phone detection (REST + voice tool), soft-delete semantics, and
the Vapi tool-call webhook contract (including that a validation failure
names the specific offending field).

### 5. Wire up the voice agent (Vapi)

1. Sign up at [vapi.ai](https://vapi.ai) and grab an API key from
   **Settings → API Keys**.
2. In **Settings → Provider Keys** (or equivalent), add your OpenAI key —
   Vapi uses your own OpenAI credentials to run the assistant's LLM
   (`gpt-4o-mini`), not a key stored in this repo or passed by our backend.
3. Expose this server publicly:
   - **Local dev:** `ngrok http 8000`, copy the `https://...ngrok...` URL.
   - **Production:** use your Render URL (see Deployment below).
4. Set `VAPI_API_KEY` and `PUBLIC_BASE_URL` in `.env`, then run:
   ```bash
   python vapi/create_assistant.py
   ```
   This creates the assistant (system prompt + tools from
   `vapi/system_prompt.md` / `vapi/tools_schema.json`, pointed at
   `{PUBLIC_BASE_URL}/vapi/webhook`) and attempts to provision a free Vapi
   phone number attached to it.
5. **If the script fails** (Vapi's REST API has shifted shape across
   versions, and free-number availability varies by account/region): open
   the Vapi dashboard, create an assistant manually, paste in the content of
   `vapi/system_prompt.md` as the system message, add the three tools from
   `vapi/tools_schema.json`, set the server URL to
   `{PUBLIC_BASE_URL}/vapi/webhook`, and attach/buy a phone number from the
   **Phone Numbers** tab. This is the documented fallback the assessment's
   own FAQ anticipates ("document what you tried and why it failed").

---

## Deployment (Render)

1. Push this repo to GitHub.
2. Create a Render **PostgreSQL** instance (free tier) — copy its internal
   connection string.
3. Create a Render **Web Service** from the repo:
   - Build command: `pip install -r requirements.txt`
   - Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
   - Env vars: `DATABASE_URL` (the Postgres connection string from step 2),
     `VAPI_WEBHOOK_SECRET` (any random string, matching the Vapi assistant
     config).
4. Once live, re-run `vapi/create_assistant.py` with `PUBLIC_BASE_URL` set
   to the Render URL (or `--assistant-id <id>` to update the existing
   assistant's `serverUrl` instead of creating a new one), so Vapi points at
   production instead of ngrok.

---

## Known Limitations & Trade-offs

- **Name validation is literal to the spec** ("alphabetic + hyphens/apostrophes"),
  so multi-word first/last names (e.g. "Mary Jane") would currently be
  rejected. A real system would likely allow spaces; kept strict here to
  match the assessment's table exactly, flagging the trade-off here instead
  of silently diverging from the written spec.
- **No authentication on the REST API.** Per the assessment's FAQ ("do not
  store real patient data... not a production healthcare system"), the API
  and dashboard are open. Adding an API key or OAuth layer would be the
  first thing to do before this touched real PHI.
- **Call transcripts aren't surfaced in the dashboard yet** — they're
  captured and persisted (`CallLog` table, linked by patient phone number)
  but there's no UI to browse them. Next step: a "View transcript" link
  next to each patient row.
- **Vapi's phone-number auto-provisioning is best-effort.** Free-number
  availability and the exact request shape vary by Vapi account/region;
  `create_assistant.py` fails loudly with the raw API response if it
  doesn't work, and the dashboard fallback is documented above.
- **Multi-language support and appointment scheduling** (both listed as
  bonus/stretch items) are not implemented. The system prompt is structured
  so language-switching could be added as a short addendum ("if the caller
  says 'hablo español', switch to Spanish for the rest of the call" — Vapi's
  transcriber/voice both support Spanish) without restructuring the
  conversation flow.

## Next Steps

- Surface `CallLog` transcripts in the dashboard.
- Add simple API-key auth in front of `/patients` and `/vapi/webhook`.
- Add Spanish-language support end-to-end (transcriber, voice, and a
  language-switch branch in the system prompt).
- Mock appointment scheduling as a fourth Vapi tool
  (`schedule_appointment`), offered after a successful registration.
