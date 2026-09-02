from fastapi import FastAPI, BackgroundTasks, Request
from pydantic import BaseModel
import os
from google import genai
from google.genai import types

app = FastAPI()

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

# Keeps track of tickets we've already processed, so duplicates are skipped (FR5).
processed_ids = set()

# Placeholder KB articles — replace with the real kb_articles.json once you have it.
KB_ARTICLES = [
    {"title": "Printer not printing", "body": "Restart the printer, check the paper tray, reinstall the driver."},
    {"title": "Email not syncing", "body": "Check internet connection, re-enter password, restart the mail app."},
]


class IncidentPayload(BaseModel):
    incident_sys_id: str
    number: str
    short_description: str
    description: str = ""
    priority: str | None = None


@app.post("/webhook")
async def webhook(payload: IncidentPayload, background_tasks: BackgroundTasks):
    # Skip if we've already handled this exact ticket (FR5).
    if payload.incident_sys_id in processed_ids:
        return {"status": "duplicate, skipped"}

    processed_ids.add(payload.incident_sys_id)

    # Hand off the slow work to run AFTER we reply (NFR1).
    background_tasks.add_task(process_incident, payload)

    return {"status": "received"}


def process_incident(payload: IncidentPayload):
    prompt = f"""
You are a support ticket triage agent. Using ONLY the knowledge articles below,
decide one action for this incident: "respond", "ask", or "escalate".

Knowledge articles:
{KB_ARTICLES}

Incident:
Short description: {payload.short_description}
Description: {payload.description}

Reply with strict JSON only, no extra text, in this exact shape:
{{"decision": "respond|ask|escalate", "message": "short message"}}
"""

    response = client.models.generate_content(
        model="gemini-flash-lite-latest",
        contents=prompt,
        config=types.GenerateContentConfig(
            http_options=types.HttpOptions(timeout=60000)
        )
    )

    print(f"Decision for {payload.number}: {response.text}")
    # Next step: parse this JSON and write it back to ServiceNow.