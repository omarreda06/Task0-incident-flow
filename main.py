from dotenv import load_dotenv
load_dotenv()

import json
import os
import requests
from fastapi import FastAPI, BackgroundTasks
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from google import genai
from google.genai import types

app = FastAPI()

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    body = await request.body()
    print("VALIDATION FAILED")
    print("Raw body received:", body)
    print("Errors:", exc.errors())
    return JSONResponse(status_code=422, content={"detail": exc.errors()})

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

# ServiceNow connection details, read from .env
SN_INSTANCE = os.environ["SN_INSTANCE"]      # e.g. dev12345.service-now.com
SN_USER = os.environ["SN_USER"]
SN_PASSWORD = os.environ["SN_PASSWORD"]
SN_CLIENT_ID = os.environ["SN_CLIENT_ID"]
SN_CLIENT_SECRET = os.environ["SN_CLIENT_SECRET"]

# Keeps track of tickets we've already processed, so duplicates are skipped (FR5).
processed_ids = set()

# The real 5 knowledge articles — Gemini must answer using only these.
KB_ARTICLES = [
    "Printer not printing: Restart the printer and unplug the cable for 30 seconds.",
    "Email not sending: Check SMTP settings and ensure port 587 is open.",
    "Cannot access system: Reset password via the 'Forgot Password' page.",
    "Slow network: Restart the router and check cable connections.",
    "Browser pages not loading: Clear cache and try incognito mode.",
]


class IncidentPayload(BaseModel):
    incident_sys_id: str
    number: str
    short_description: str
    description: str | None = ""
    priority: int | None = None


@app.post("/webhook")
async def webhook(payload: IncidentPayload, background_tasks: BackgroundTasks):
    if payload.incident_sys_id in processed_ids:
        return {"status": "duplicate, skipped"}

    processed_ids.add(payload.incident_sys_id)

    background_tasks.add_task(process_incident, payload)

    return {"status": "received"}


def process_incident(payload: IncidentPayload):
    articles_text = "\n".join(f"- {a}" for a in KB_ARTICLES)

    prompt = f"""You are a support ticket triage agent. Using ONLY the knowledge articles below,
decide one action for this incident: "respond", "ask", or "escalate".

Rules:
- If an article clearly and specifically covers the problem, choose "respond" and give the fix as the message.
- If the ticket is too vague to match confidently to an article, choose "ask" and write a clarifying question as the message.
- If no article covers the topic at all, choose "escalate" and briefly say why as the message.

Knowledge articles:
{articles_text}

Incident:
Short description: {payload.short_description}
Description: {payload.description}

Reply with strict JSON only, no extra text, in this exact shape:
{{"decision": "respond|ask|escalate", "message": "short message"}}
"""

    try:
        response = client.models.generate_content(
            model="gemini-flash-lite-latest",
            contents=prompt,
            config=types.GenerateContentConfig(
                http_options=types.HttpOptions(timeout=60000)
            )
        )
    except Exception as e:
        print(f"ERROR: Gemini call failed for {payload.number}: {e}")
        return

    try:
        text = response.text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        decision_data = json.loads(text)
    except (json.JSONDecodeError, AttributeError) as e:
        print(f"ERROR: Could not parse Gemini's response for {payload.number}: {e}")
        print(f"Raw response was: {response.text}")
        return

    decision = decision_data.get("decision")
    message = decision_data.get("message", "")

    if decision not in {"respond", "ask", "escalate"}:
        print(f"ERROR: Invalid decision value from Gemini for {payload.number}: {decision_data}")
        return

    print(f"Decision for {payload.number}: {decision_data}")

    write_back_to_servicenow(payload.incident_sys_id, decision, message)


def get_servicenow_token() -> str:
    """Gets a fresh OAuth access token from ServiceNow (Basic Auth is blocked on this instance)."""
    response = requests.post(
        f"https://{SN_INSTANCE}/oauth_token.do",
        data={
            "grant_type": "password",
            "client_id": SN_CLIENT_ID,
            "client_secret": SN_CLIENT_SECRET,
            "username": SN_USER,
            "password": SN_PASSWORD,
        },
        timeout=15,
    )
    response.raise_for_status()
    return response.json()["access_token"]


def write_back_to_servicenow(sys_id: str, decision: str, message: str):
    url = f"https://{SN_INSTANCE}/api/now/table/incident/{sys_id}"

    if decision == "respond":
        body = {
            "work_notes": message,
            "close_notes": message,
            "close_code": "Solved (Permanently)",
            "state": "6",
        }
    elif decision == "ask":
        body = {
            "comments": message,
        }
    else:  # escalate
        body = {
            "work_notes": f"Escalated: {message}",
        }

    try:
        token = get_servicenow_token()
        resp = requests.patch(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json=body,
            timeout=15,
        )
        resp.raise_for_status()
        print(f"Wrote '{decision}' decision back to ServiceNow for sys_id {sys_id}")
    except Exception as e:
        print(f"ERROR: Failed to write back to ServiceNow: {e}")