#!/usr/bin/env python3
"""Provisions (or updates) the Vapi assistant and, optionally, a phone number
for it, wiring everything to this FastAPI backend's webhook.

Usage:
    python vapi/create_assistant.py                 # create a new assistant
    python vapi/create_assistant.py --assistant-id X # update an existing one
    python vapi/create_assistant.py --no-phone-number

Requires VAPI_API_KEY and PUBLIC_BASE_URL in the environment (.env is loaded
automatically). PUBLIC_BASE_URL must be a URL Vapi can reach over the public
internet -- an ngrok https URL for local dev, or your Render URL once
deployed.

This is a best-effort convenience script, not something this repo's CI
depends on: Vapi's REST API has changed shape across versions, and the exact
request body here (voice provider, phone-number provisioning) may need small
tweaks depending on your account tier and region. If a call fails, the
script prints the full response body -- cross-reference it against
https://docs.vapi.ai/api-reference and finish the step in the Vapi dashboard
instead. The dashboard is the authoritative fallback for every step here.
"""

import argparse
import json
import os
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).parent
VAPI_BASE_URL = "https://api.vapi.ai"

FIRST_MESSAGE = (
    "Hi, thanks for calling Lakeview Family Clinic! I can help you register "
    "as a new patient today -- should only take a couple of minutes. Can I "
    "start with your first and last name?"
)


def load_env():
    env_path = ROOT.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def load_system_prompt() -> str:
    text = (ROOT / "system_prompt.md").read_text()
    # The file opens with a short explanation of *why* the prompt is
    # structured this way, aimed at a human reading the repo. Only the part
    # after the first "---" is the actual instruction text sent to the LLM.
    marker = "\n---\n"
    if marker in text:
        return text.split(marker, 1)[1].strip()
    return text.strip()


def load_tools() -> list:
    return json.loads((ROOT / "tools_schema.json").read_text())


def build_assistant_payload(server_url: str) -> dict:
    return {
        "name": "Lakeview Patient Registration Agent",
        "firstMessage": FIRST_MESSAGE,
        "model": {
            "provider": "openai",
            "model": "gpt-4o-mini",
            "temperature": 0.4,
            "messages": [{"role": "system", "content": load_system_prompt()}],
            "tools": load_tools(),
        },
        "voice": {
            "provider": "playht",
            "voiceId": "jennifer",
        },
        "transcriber": {
            "provider": "deepgram",
            "model": "nova-2",
            "language": "en-US",
        },
        "serverUrl": server_url,
        "endCallFunctionEnabled": True,
        "silenceTimeoutSeconds": 30,
        "maxDurationSeconds": 900,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assistant-id", help="Update this existing assistant instead of creating a new one")
    parser.add_argument("--no-phone-number", action="store_true", help="Skip provisioning a phone number")
    args = parser.parse_args()

    load_env()

    api_key = os.environ.get("VAPI_API_KEY")
    base_url = os.environ.get("PUBLIC_BASE_URL")
    webhook_secret = os.environ.get("VAPI_WEBHOOK_SECRET")

    if not api_key:
        sys.exit("VAPI_API_KEY is not set (check your .env file).")
    if not base_url or base_url.startswith("http://localhost"):
        print(
            "WARNING: PUBLIC_BASE_URL is not set to a publicly reachable URL "
            "(got %r). Vapi needs to be able to reach this server over the "
            "internet to call your tools -- use an ngrok https URL for local "
            "dev, or your Render URL once deployed." % base_url,
            file=sys.stderr,
        )

    server_url = f"{base_url.rstrip('/')}/vapi/webhook"
    payload = build_assistant_payload(server_url)
    if webhook_secret:
        payload["serverUrlSecret"] = webhook_secret

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    with httpx.Client(base_url=VAPI_BASE_URL, headers=headers, timeout=30) as client:
        if args.assistant_id:
            resp = client.patch(f"/assistant/{args.assistant_id}", json=payload)
        else:
            resp = client.post("/assistant", json=payload)

        if resp.status_code >= 300:
            print(f"Vapi API error ({resp.status_code}):", file=sys.stderr)
            print(resp.text, file=sys.stderr)
            sys.exit(1)

        assistant = resp.json()
        assistant_id = assistant["id"]
        print(f"Assistant ready: {assistant_id}")
        print(f"  serverUrl -> {server_url}")

        if args.no_phone_number:
            return

        phone_resp = client.post("/phone-number", json={"provider": "vapi", "assistantId": assistant_id})
        if phone_resp.status_code >= 300:
            print(
                "\nCould not auto-provision a phone number "
                f"({phone_resp.status_code}): {phone_resp.text}\n"
                "This is commonly because free Vapi numbers are limited per "
                "account/region. Provision one manually in the Vapi "
                "dashboard under Phone Numbers, and attach it to assistant "
                f"{assistant_id}.",
                file=sys.stderr,
            )
            return

        phone = phone_resp.json()
        print(f"Phone number provisioned: {phone.get('number')}")


if __name__ == "__main__":
    main()
