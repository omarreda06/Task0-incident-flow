from dotenv import load_dotenv
load_dotenv()

import json
import os
from fastapi import FastAPI, BackgroundTasks
from pydantic import BaseModel
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
        # Gemini sometimes wraps JSON in markdown code fences — strip those if present.
        text = response.text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        decision_data = json.loads(text)
    except (json.JSONDecodeError, AttributeError) as e:
        print(f"ERROR: Could not parse Gemini's response for {payload.number}: {e}")
        print(f"Raw response was: {response.text}")
        return

    if decision_data.get("decision") not in {"respond", "ask", "escalate"}:
        print(f"ERROR: Invalid decision value from Gemini for {payload.number}: {decision_data}")
        return

    print(f"Decision for {payload.number}: {decision_data}")
    # Next step: write decision_data back to ServiceNow.