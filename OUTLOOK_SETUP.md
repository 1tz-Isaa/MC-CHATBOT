# Outlook news setup

The chatbot imports messages only from a top-level Outlook folder named
`MC News`. Microsoft still grants the application delegated `Mail.Read`
permission for the mailbox, but this project's code queries only that folder.

## 1. Prepare Outlook

1. Create a top-level mail folder named `MC News`.
2. Create an Outlook rule that moves the school announcements/newsletters you
   want the chatbot to use into that folder.
3. Do not route private messages into this folder.

## 2. Register the local chatbot

1. Open the Microsoft Entra admin center.
2. Go to **App registrations** and create a new registration.
3. For a school-only app, choose accounts in this organizational directory.
4. Under **API permissions**, add Microsoft Graph delegated permission
   `Mail.Read`.
5. Under **Authentication**, enable **Allow public client flows**.
6. Copy the **Application (client) ID** and **Directory (tenant) ID**.

Your school Microsoft administrator may need to approve app registration or
mail permission.

## 3. Configure and sign in

From the project directory:

```bash
cp .env.example .env
```

Open `.env` and replace the example client and tenant IDs. If you use multiple
Microsoft accounts, set `OUTLOOK_ACCOUNT` to the intended mailbox address.
Then run:

```bash
source .venv/bin/activate
python outlook_news.py --login
```

Follow the printed Microsoft device-login link and code. The project never asks
for or stores your Outlook password. Its cached sign-in token is saved under
`.private/`, which is excluded from Git.

After the first sign-in, run the chatbot normally:

```bash
python main.py
```

The chatbot checks for updates in the background, refreshing Outlook news at
most once per hour by default. Change `OUTLOOK_REFRESH_HOURS` in `.env` if a
different interval is preferred. Messages are limited to the configured folder
and `OUTLOOK_LOOKBACK_DAYS` (90 days by default); attachments are not imported.

To refresh independently of the chatbot, or use the same command in a daily
local scheduled task:

```bash
.venv/bin/python sync_data.py
```

This refresh does not require Ollama. The changed records are indexed on the
next general question, or immediately with `sync_data.py --index` when Ollama
is running. A local Codex scheduled task requires the computer to be awake and
the desktop app running.

## Connection status and recovery

Use `/status` inside the chatbot, or run either of these read-only commands:

```bash
.venv/bin/python outlook_news.py --status
.venv/bin/python sync_data.py --status
```

The status distinguishes missing configuration, a required sign-in, an error,
and current or stale news, and shows the last successful update. If sign-in
expires, run `python outlook_news.py --login` again. Scheduled refreshes never
open an interactive login. A failed refresh keeps the last saved news instead
of clearing it. A successful empty folder produces an empty news CSV.

Only intentionally selected school news should enter `MC News`: those messages
become searchable chatbot records, including their subject, body, sender, date,
and Outlook link. Tokens, generated news, and status files stay local and are
excluded from Git. Token files are written atomically with owner-only access.
