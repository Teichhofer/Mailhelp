# Initial setup <!-- mailhelp-id:ersteinrichtung/ersteinrichtung -->

Verified for Mailhelp 7.0. This guide leads from an empty directory to the first
checked suggestion. It applies to Windows 11 and Linux; deviations for Docker are marked.

**Goal:** Mailhelp is running, is reachable in the browser, reads a mailbox, has an AI connection
and knows Calendar and task list. An external entry occurs only after your
explicit confirmation.

## Prerequisites <!-- mailhelp-id:ersteinrichtung/voraussetzungen -->

- Python 3.12 (Windows: `py -3.12`, Linux: `python3.12`) or Docker with Compose.
- Credentials of an IMAP mailbox (server, port, username, password or app password).
- A key for OpenRouter **or** a locally running Ollama server.
- Optional: access to Google Calendar/Todoist, Outlook/Microsoft To Do or a
  CalDAV server; optionally a Telegram bot with your user and chat ID.

## 1. Install <!-- mailhelp-id:ersteinrichtung/1-installieren -->

**Windows 11** (PowerShell in the Mailhelp directory):

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.lock
.venv\Scripts\python -m pip install --no-deps -e .
```

**Linux:**

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install --no-deps -e .
```

**Docker:** no installation necessary; continue with Stage 2.

## 2. Start and read the terminal code <!-- mailhelp-id:ersteinrichtung/2-starten-und-den-terminal-code-ablesen -->

Without `config.yaml`, Mailhelp starts the protected setup assistant.

- Windows: `.venv\Scripts\mailhelp --config-directory .`
- Linux: `.venv/bin/mailhelp --config-directory .`
- Docker: `docker compose -f compose.setup.yaml up --build`

**Result:** The terminal shows a one-time code and the address `http://localhost:8765`.
If the code is missing, request a new one with `mailhelp --pair --config-directory .` (Docker:
`docker compose exec mailhelp mailhelp --pair --config-directory /config`).

## 3. Pair in the browser <!-- mailhelp-id:ersteinrichtung/3-im-browser-koppeln -->

1. Open `http://localhost:8765/einrichtung/start`.
2. Enter the code in **Code from the Mailhelp console** and select **Pair device**.

**Result:** The page “Set up Mailhelp: Web access and time zone” appears (Stage 1 of 5).

## 4. Run through wizard <!-- mailhelp-id:ersteinrichtung/4-assistent-durchlaufen -->

Each stage has **Check** and **Save and continue**; via the stage list you can go back at any time. **Check** tests the entered values and saves nothing. The result appears above the form: for a problem, cause, affected field (with link to it), and concrete steps for resolution. The entered values remain, passwords are never displayed again. Password fields remain displayed empty: **Empty: keep saved value**. At most ten checks per minute are possible to avoid account locks at the email provider.

1. **Web access and time zone:** Check **Time zone** (e.g. `Europe/Berlin`) and set a **Web password (at least 12 characters)**.
2. **Mailbox:** Enter **IMAP server**, **Port**, **Encryption** (`ssl` usually port 993, `starttls` usually 143), username (`IMAP_USERNAME`), and password (`IMAP_PASSWORD`) and select **Check**. Then select **Inbox** and **Drafts folder** from the found folder list.
3. **AI provider:** `openrouter` with `OPENROUTER_API_KEY` or `ollama` with **Ollama address (HOST:PORT)**; select **Check**.
4. **Calendar and Tasks:** Select **Calendar service** and **Task service** and enter the matching identifier (**Google Calendar ID**, **Todoist project ID**, **CalDAV calendar address**, **CalDAV task address**, **Outlook Calendar ID**, **Microsoft To Do list**). For Google and Microsoft, **Connect Google** and **Connect Microsoft** are available respectively. Details: [Settings, Targets section](Web-Einstellungen.md#ziele).
5. **Completion:** **Check all** shows every stage with ✓ or ✗ and a link to it. Check **Save configuration and start normal operation** and select **Save and start**. If a check fails, the same overview appears and nothing is activated.

**Result:** “Setup completed”. `config.yaml` and `.env` are saved; the credentials are only in `.env`.

## 5. Sign In and Check Connections <!-- mailhelp-id:ersteinrichtung/5-anmelden-und-verbindungen-pruefen -->

1. Open `http://localhost:8765/anmelden` and sign in with the web password. You pair additional devices with **Send code via Telegram** (when Telegram is active) or a new terminal code.
2. Open **Settings → Check connections**: The checks only read and change nothing.
3. Under **Status** you see the last contact per service; the mailbox appears after the first email retrieval.

## 6. Recognize Saved and Active State <!-- mailhelp-id:ersteinrichtung/6-gespeicherten-und-aktiven-stand-erkennen -->

In **Settings**, each setting shows “active” or “saved – takes effect only after a restart” or “… at the next safe point”. Restart: **Settings → Restart Mailhelp**.

## 7. First Test Case <!-- mailhelp-id:ersteinrichtung/7-erster-testfall -->

1. Send an email with a clear request to yourself, e.g., “Please send the form back by Friday.”
2. After the next retrieval, a suggestion with Evidence appears under **Open**.
3. Select **Add as task** (for Events, **Add to calendar**). Mailhelp first reports “Saved – the entry will be verified with the provider” and after the verification retrieval “Created and verified”.

For a run without a real entry, set `test_mode: true`: confirmations are then only simulated.

## If something does not work <!-- mailhelp-id:ersteinrichtung/wenn-etwas-nicht-klappt -->

| Message or situation | Next step |
| --- | --- |
| “Mailhelp is already running …” | Quit the running instance via **Settings → Quit Mailhelp** or with Ctrl+C |
| Code expired or forgotten | `mailhelp --pair --config-directory .` |
| Mailbox check fails | The message above the form states the cause and field; see the table below |
| Web password forgotten | On the computer `mailhelp --reset-web-password --config-directory .` |
| Docker: file permissions under Linux | `mkdir -p data logs` and `sudo chown 65532:65532 data logs` |

### Common messages during Check (from 6.1) <!-- mailhelp-id:ersteinrichtung/haeufige-meldungen-beim-pruefen-ab-61 -->

**Check** states the cause, the affected field, and concrete steps for a problem. The
most common cases:

| Message | What usually helps |
| --- | --- |
| The IMAP server is not known under this name. | Check the spelling, enter only the server name without `https://` |
| The IMAP server does not respond on this port. | Port 993 with `ssl` or 143 with `starttls`; check firewall |
| Port and encryption do not match. | 993 belongs to `ssl`, 143 to `starttls` |
| The server rejected the login. | Full email address as username; for two-factor authentication an app password; enable IMAP in webmail |
| The specified inbox was not found. | Select one of the mentioned folders, usually `INBOX` |
| OpenRouter did not accept the key. | Copy the key completely (starts with `sk-or-`) |
| No credit or limit remains for this key. | Top up credit or increase limit |
| Ollama does not respond at this address. | Start `ollama serve`; from Docker `http://host.docker.internal:11434` |
| The Google authorization has expired or was revoked. | Run **Connect Google** again (required after 7 days in the Google app's test mode) |
| The Google Calendar API is disabled for the Google project. | Enable the Calendar API in the Google Cloud Console |
| Calendar, list, or project was not found. | Select calendar or check Todoist project ID |
| Too many checks in a short time. | Wait one minute (protection against account blocks at the email provider) |

Next: [Manage accounts](Konten-verwalten.md), [Settings](Web-Einstellungen.md).
