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
gemini = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

SN_INSTANCE = os.environ["SN_INSTANCE"]
SN_USER = os.environ["SN_USER"]
SN_PASSWORD = os.environ["SN_PASSWORD"]
SN_CLIENT_ID = os.environ["SN_CLIENT_ID"]
SN_CLIENT_SECRET = os.environ["SN_CLIENT_SECRET"]

processed_ids = set()

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


@app.exception_handler(RequestValidationError)
async def on_validation_error(request, exc):
    print("Bad request body:", await request.body())
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


@app.post("/webhook")
async def webhook(payload: IncidentPayload, background_tasks: BackgroundTasks):
    if payload.incident_sys_id in processed_ids:
        return {"status": "duplicate"}

    processed_ids.add(payload.incident_sys_id)
    background_tasks.add_task(handle_incident, payload)
    return {"status": "received"}


def handle_incident(payload: IncidentPayload):
    decision, message = ask_gemini(payload)
    if decision:
        update_servicenow(payload.incident_sys_id, decision, message)


def ask_gemini(payload: IncidentPayload):
    articles = "\n".join(f"- {a}" for a in KB_ARTICLES)

    prompt = f"""You are a support ticket triage agent. Using ONLY the knowledge articles below,
decide one action for this incident: "respond", "ask", or "escalate".

Rules:
- If an article clearly covers the problem, choose "respond" and give the fix as the message.
- If the ticket is too vague to match confidently, choose "ask" and write a clarifying question.
- If no article covers the topic, choose "escalate" and briefly say why.

Knowledge articles:
{articles}

Incident:
Short description: {payload.short_description}
Description: {payload.description or "No additional details provided."}

Reply with strict JSON only: {{"decision": "respond|ask|escalate", "message": "short message"}}
"""

    try:
        response = gemini.models.generate_content(
            model="gemini-flash-lite-latest",
            contents=prompt,
            config=types.GenerateContentConfig(http_options=types.HttpOptions(timeout=60000)),
        )
        text = response.text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        data = json.loads(text)
        decision = data.get("decision")
        message = data.get("message", "")
    except Exception as e:
        print(f"Gemini error for {payload.number}: {e}")
        return None, None

    if decision not in {"respond", "ask", "escalate"}:
        print(f"Bad decision from Gemini for {payload.number}: {data}")
        return None, None

    print(f"Decision for {payload.number}: {decision} - {message}")
    return decision, message


def get_servicenow_token():
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


def update_servicenow(sys_id: str, decision: str, message: str):
    body_by_decision = {
        "respond": {
            "work_notes": message,
            "close_notes": message,
            "close_code": "Solved (Permanently)",
            "state": "6",
        },
        "ask": {"comments": message},
        "escalate": {"work_notes": f"Escalated: {message}"},
    }
    body = body_by_decision[decision]

    try:
        token = get_servicenow_token()
        response = requests.patch(
            f"https://{SN_INSTANCE}/api/now/table/incident/{sys_id}",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=body,
            timeout=15,
        )
        response.raise_for_status()
        print(f"Wrote '{decision}' back to ServiceNow for {sys_id}")
    except Exception as e:
        print(f"ServiceNow write-back error: {e}")