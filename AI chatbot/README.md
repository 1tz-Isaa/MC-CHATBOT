# MC AI

Local MVP chatbot for Malden Catholic built to run on a laptop with Ollama.

THIS IS JUST THE TEST VERSION FOR THE CHATBOT

## What it does

- Uses the local `gemma3:4b` model already installed in Ollama.
- Answers only from approved school data files and the local catalog database.
- Shows source links for official pages and labels local data separately.
- Keeps rooms, schedules, staff contacts, news, and sports in local files instead of retraining a model.
- Supports a raw intake flow so messy collector submissions can be staged before approval.

## Quick map

This section is the easiest way to understand the project.

- `MODEL`: Ollama runs the language model. This is the chat brain.
- `APP`: `app.py` is the main backend. It receives user questions and returns answers.
- `CATALOG`: `catalog.py` is the local database layer. It stores and loads structured school data.
- `DATA`: the `data/` folder is the source of truth for school information you enter manually.
- `INTAKE`: the `scripts/` folder is where you add news or events into the system.
- `UI`: the `static/` folder is the website/chat page the user sees.
- `OUTLOOK`: optional future import. Ignore this for now unless the school approves it.

## If you want to change something

- `Change chatbot behavior`: edit `app.py`
- `Change how data is stored`: edit `catalog.py`
- `Add or fix room / teacher / class / office records`: edit `data/catalog_seed.json`
- `Add local room or staff notes`: edit `data/local_resources.json`
- `Add daily announcements manually`: run `scripts/add_manual_news.py`
- `Add school events manually`: run `scripts/add_manual_event.py`
- `Rebuild the local database`: run `scripts/rebuild_catalog.py`
- `Change the website look`: edit files in `static/`
- `Ignore for now`: `data/outlook_import_config.json` and `scripts/import_outlook_news.py`

## Project layout

- `app.py`: main chatbot backend
- `catalog.py`: local database + catalog logic
- `data/official_resources.json`: official website facts already added
- `data/local_resources.json`: extra local notes and placeholder campus info
- `data/catalog_seed.json`: approved structured school records
- `data/raw_submissions.json`: raw or newly added records before/while rebuilding
- `data/outlook_import_config.json`: future Outlook config, safe to ignore for now
- `scripts/rebuild_catalog.py`: rebuild local database from the data files
- `scripts/add_manual_news.py`: manual daily-news intake
- `scripts/add_manual_event.py`: manual school-event intake
- `scripts/import_outlook_news.py`: future Outlook importer, safe to ignore for now
- `static/`: frontend chat page

## Setup

1. Create a virtual environment:

   ```bash
   python3 -m venv .venv
   ```

2. Activate it:

   ```bash
   source .venv/bin/activate
   ```

3. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

4. Make sure Ollama is running:

   ```bash
   ollama serve
   ```

5. Verify the model is available:

   ```bash
   ollama list
   ```

   This app defaults to `gemma3:4b`. If you do not have it, pull it with:

   ```bash
   ollama pull gemma3:4b
   ```

6. Start the app:

   ```bash
   uvicorn app:app --reload
   ```

7. Open `http://127.0.0.1:8000`.

8. If you edit catalog seed data or raw submissions, rebuild the catalog:

   ```bash
   ./.venv/bin/python scripts/rebuild_catalog.py
   ```

## Manual daily news import

This is the recommended path if Outlook auth is blocked by school permissions.

Interactive mode:

```bash
./.venv/bin/python scripts/add_manual_news.py
```

Direct arguments:

```bash
./.venv/bin/python scripts/add_manual_news.py \
  --title "Daily Announcements 3.24.26" \
  --body "Tomorrow is an early dismissal. Check with your teachers for schedule changes."
```

This writes an approved local `news_item` into the raw intake file and rebuilds the catalog automatically.

## Manual event calendar import

This is the local-first path for school calendar events already known by staff or copied from the website.

Interactive mode:

```bash
./.venv/bin/python scripts/add_manual_event.py
```

Direct arguments:

```bash
./.venv/bin/python scripts/add_manual_event.py \
  --title "Open House" \
  --summary "Admissions open house for prospective families." \
  --event-date "2026-04-10" \
  --start-time "18:00" \
  --location "Main Building"
```

This writes an approved local `event` into the raw intake file and rebuilds the catalog automatically.

## Outlook daily announcements import

UNDER CONSTRUCTION 

Use this when daily announcements come from a single Outlook sender and a predictable subject line.

1. Create a Microsoft Entra app registration for a public client.
2. Add delegated Microsoft Graph permission `Mail.Read`.
3. Copy the app's client ID into `data/outlook_import_config.json`.
4. Confirm the sender rule and subject regex in `data/outlook_import_config.json`.
5. Run the importer:

   ```bash
   ./.venv/bin/python scripts/import_outlook_news.py
   ```

6. Complete the device-code sign-in in the browser when prompted.
7. Re-open the chatbot or call the health endpoint to confirm the imported news is now in the local catalog.

Notes:

- This importer does not store your Outlook password.
- It stores a local token cache in `data/.msal_token_cache.json`.
- Imported messages are filtered by sender and subject before becoming local `news_items`.
- If your school Outlook account blocks user consent, a Microsoft 365 admin may need to approve the app once.

## Customizing the bot

- Add campus room info to `data/local_resources.json`.
- Add approved staff emails and office locations to `data/local_resources.json`.
- Add the real bell schedule before letting students rely on schedule answers.
- Add approved structured records to `data/catalog_seed.json`.
- Put messy or unreviewed collector submissions into `data/raw_submissions.json`.
- Use `scripts/add_manual_event.py` for school events you want the bot to answer from locally.
- Use `source_system` values like `manual`, `outlook`, or `sportsyou` so you can sync those later.

## Notes

- This is intentionally read-only.
- It does not connect to grades, attendance, or student records.
- If a question is not covered by the approved data, the bot should say it does not know yet.
- Outlook and SportsYou are optional future inputs. The local-first version works without either account by using manual or approved imports.
