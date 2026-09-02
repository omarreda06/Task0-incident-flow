# Agentic Incident Flow

This is my submission for Task 0 of the Sprints x BARQ Systems AI Engineering Internship.

The idea: when someone opens a support ticket in ServiceNow, it gets sent automatically to a small service I built, which asks Gemini what to do with it (respond, ask for more info, or escalate to a human) and then writes that decision back onto the same ticket. No manual steps in between.

## Demo Video

[Watch the demo here](https://drive.google.com/file/d/1aimbgrgF30SV5WQGhbh4KXvKVLwvlD7q/view?usp=sharing)

## How it works

- A new incident is created in ServiceNow.
- A Business Rule fires automatically and sends the ticket's details to my FastAPI service as JSON.
- The service replies immediately so ServiceNow doesn't wait around, then in the background sends the ticket text plus five knowledge articles to Gemini.
- Gemini responds with a decision (respond, ask, or escalate) and a short message, based only on those knowledge articles.
- The service writes that decision back onto the original ticket through ServiceNow's API.

## What's working

- The /webhook endpoint accepts a ticket, replies fast, and processes the Gemini call in the background.
- Gemini sends back a decision in strict JSON, grounded only in the five knowledge articles.
- Duplicate protection, so the same ticket only gets processed once.
- Writing the decision back to ServiceNow: respond resolves the ticket with the fix, ask posts a clarifying question as a comment, escalate adds a work note.
- All three test cases from test_incidents.json pass (printer -> respond, vague email -> ask, leave request -> escalate).
- API keys and ServiceNow credentials are read from a .env file, so nothing secret is committed.

One thing worth knowing: this ServiceNow instance blocks the plain username and password login (Basic Auth) by default now, so the write-back step uses OAuth instead. That part took a while to figure out, more on that in reflection.md.

## Running it yourself

You'll need Python 3.11+, a free Gemini API key from Google AI Studio, and your own ServiceNow developer instance.

```
git clone https://github.com/omarreda06/incident-flow.git
cd incident-flow
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

Copy .env.example to .env and fill in your own values:

```
GEMINI_API_KEY=
SN_INSTANCE=
SN_USER=
SN_PASSWORD=
SN_CLIENT_ID=
SN_CLIENT_SECRET=
```

Then start the server:

```
uvicorn main:app --reload
```

To connect it to a real ServiceNow instance, follow pdi_guide.md in this repo for setting up the PDI, exposing your local service with ngrok, and creating the Business Rule (business_rule.js is ready to paste in, just swap in your own ngrok URL).

You can also test it without ServiceNow at all:

```
Invoke-RestMethod -Uri "http://127.0.0.1:8000/webhook" -Method Post -ContentType "application/json" -Body '{"incident_sys_id": "1", "number": "INC001", "short_description": "Printer not printing", "description": "Paper jam error but no paper is stuck.", "priority": 3}'
```

Check the terminal running uvicorn after a few seconds, it'll print the decision Gemini made.

## What's in this repo

- main.py - the actual service
- prompt.txt - the exact Gemini prompt, as sent
- kb_articles.json, payload_contract.json, test_incidents.json, business_rule.js, pdi_guide.md - the asset pack files provided for this task
- screenshots/ - Business Rule setup plus before and after shots for all three decision types
- reflection.md - what was hard and what I'd improve
- .env.example - list of environment variables needed, empty values

## Notes to self

- Gemini model names keep changing, if something 404s, there's a list_models.py script I used earlier to check what's currently available.
- Windows PowerShell doesn't understand real curl syntax, use Invoke-RestMethod instead like the example above.
- If ServiceNow's OAuth token request fails, double check the Client Secret in .env matches exactly what's shown in Application Registry, that one cost me a lot of time.
