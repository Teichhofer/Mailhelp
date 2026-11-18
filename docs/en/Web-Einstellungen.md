# Web interface settings <!-- mailhelp-id:web-einstellungen/einstellungen-der-weboberflaeche -->

Verified for Mailhelp 7.0; inventory of all keys: [Test report 7.0](../Pruefung-Dokumentation-7.0.md).

## Topics overview <!-- mailhelp-id:web-einstellungen/themenuebersicht -->

`/themen` shows relevant topics and exclusion topics in separate tabs with counts.
Search searches name, ID, description, examples and exclusions; the status filter shows
all, active or deactivated topics. Without JavaScript, select “Search topics”; with JavaScript,
filtering happens immediately. The table becomes a card list on small screens.
Deactivated topics appear at the end. “Change pending” marks queued topic commands.
“Edit” and “New topic” each open a separate page. Existing mailbox areas
are only displayed and retained from the current file when saving. In examples and
exclusions, there is one entry per line; a semicolon remains part of the entry.

### Edit topic <!-- mailhelp-id:web-einstellungen/thema-bearbeiten -->

1. In the overview, select “Edit” or “New topic”.
2. Adjust name, description, examples and exclusions; switch “Active” on or off.
   For a new topic, the topic ID is suggested from the name and can be changed before the
   first save. The ID of an existing topic remains fixed.
3. Select “Review change”. The preview shows the previous and the
   new value for each changed field; new and removed examples are marked with “+ new” and “− removed”,
   unchanged fields are opened by “Show unchanged fields”. The preview does not save anything yet.
4. Check “Explicitly save change” and select “Save change”. With
   “Continue editing” you return without saving.

Errors are in Deutsch directly on the affected field and in a focused
summary with links to the inputs. Field help and errors are linked
with the inputs for assistive technologies. The inputs are retained. If the
topic file has been changed in the meantime, select “Reload” and review the change again. An
open preview appears in the overview under “Pending topic changes” and expires
after 24 hours. The last active relevant topic cannot be deactivated.

Exclusion topics are negative categories for Learning and decision tests. In normal
Email operation, the relevant topics and their exclusions take effect; the file is not another
global Prefilter.

From 5.7, Learning (`/lernen`) bundles the functions “Learn from Mailbox”
(`/lernen/postfach`) and “Learn from decisions” (`/lernen/entscheidungen`).
The topic page also links rule learning. `/themen/lernen` is permanently
redirected; old open POST forms do nothing and require a new confirmation.
It analyzes existing logged decisions after explicit approval of
costs and data transfer. Old and New stand side by side; selected rules can
be edited as fields or complete topic YAML. From 5.8, “Review selected changes” creates
a separate persistent review state of the edited values;
only “Take reviewed changes” with explicit confirmation takes exactly this state.
Parser, schema, session and revision checks protect both topic files. If a
write is aborted, the approved takeover can be completed without a new AI analysis.
Guide: [Learn from decisions](Bedienung.md#aus-entscheidungen-lernen).

From 5.8, the confirmation of a setting shows the readable name, “Previously saved”,
“New” and the concrete effectiveness. Warnings refer to the respective setting.
The Status page separates browser connection from integration state and first offers
action required and the read-only self-test; operation details and counters are expandable.

There are no new `config.yaml` switches for this. The optional prompt
`decision_rule_learning` is in `prompts.yaml`, uses the active model route and the
existing AI limits. Older prompt files remain valid; if the block is missing, the
analysis is ended with a note. External Calendar and task lists are not written to.

`/einstellungen` shows tiles for accounts, general rules, content and system actions.
Account tiles state the number of accounts set up in the running service. Area tiles
mark saved, not yet active changes. Comparison is with the values that the
next start would apply: A setting missing in `config.yaml` counts with its
default value and is not a pending change. The Search (`?suche=…`, at most 80 characters)
finds Settings and pages (Mailboxes, IServ, target profiles, credentials, topics, Devices,
restart …) whose name, key, group, area, help text or synonyms contain all
entered words. Capitalization, whitespace and umlauts (`ä`/`ae`, `ß`/`ss`) do
not count; synonyms connect e.g. “AI” and “model”, “Mailbox” and “account”, “retrieval” and
“interval”. First are exact keys or names, then word beginnings, then remaining
matches, in case of a tie alphabetically. Each match leads with an anchor
(`#einstellung-<schlüssel>`) directly to the setting and expands it.

Live Search (5.3): On the overview and every area page, typing from the first
character shows up to ten matches directly under the search field, without clicking “Search” and without a new
page. Search is performed 150 ms after the last input; a new input cancels the previous request,
late responses are discarded. An announcement states the number of matches. Clearing removes the
matches immediately; “Search” or Enter still opens the full results page. On an
error, normal Search remains usable. The instant search never calls the AI and reads only
names and help texts, no saved values. Endpoint:
`GET /api/einstellungen/suche?suche=…` (authenticated only, not cached).
An unknown area returns HTTP 404. The interface works without JavaScript.

| Area | Address | Content |
| --- | --- | --- |
| Email retrieval | `?bereich=abruf` | Retrieval, Email limits, Time limits, Repetitions |
| Notifications | `?bereich=benachrichtigungen` | Telegram, Daily overview, Push control |
| Replies and Events | `?bereich=antworten` | Replies, Event durations, Review, Goals |
| AI and Statistics | `?bereich=ki` | Model table (read-only), Images, Learning, Reports, Costs |
| Data and logs | `?bereich=daten` | Attachments, Retention, Logging |
| Web interface and System | `?bereich=system` | Sessions, Network, Devices, Restart, Exit |
| Credentials | `?bereich=zugangsdaten` | Passwords and API keys |

### Edit topic <!-- mailhelp-id:web-einstellungen/thema-bearbeiten-2 -->

On large screens, the section navigation remains reachable next to the values;
on mobile, it is located above the settings groups. Saving and confirmation
continue to run via `/einstellungen/speichern` and the command queue.

## Add mailbox (3.5) <!-- mailhelp-id:web-einstellungen/postfach-hinzufuegen-35 -->

Under `/einstellungen/postfaecher`, enter server, port, SSL/TLS, STARTTLS or unencrypted connection,
username, password, source folder and draft folder together. The first source folder
is the inbox. The start limit is pre-filled with today (00:00 in the configured
time zone); empty means all existing mails. **Check connection and activate mailbox**
checks login, folder list and read access. Duplicate accounts (including deactivated ones) are
rejected. Error messages contain no server responses or credentials; remaining inputs
are retained, the password field is cleared.

Only after successful checking are `config.yaml` and `.env` saved. New readers are
added between mail cycles, including mailbox labels, metrics, reply drafts and
mailbox filters. Connection errors during reloading let the existing readers continue running and
are retried in the next cycle. Saved accounts are active even after a restart.
Empty access fields use already stored `IMAP_<id>_USERNAME`/`IMAP_<id>_PASSWORD`.
Process variables take precedence; conflicting inputs are rejected.

Session, CSRF, draft version, configuration and `.env` hash as well as idempotency key are
checked; the session again immediately before writing. Interrupted activations are
not executed again with the same key: reload the page and check the saved state.
Other drafts are retained. The cards distinguish active, deactivated, draft,
saved with pending activation and changes in draft. The collapsed alternative
**Add as draft only instead** remains available. Changes to and removal of existing
mailboxes still require draft adoption and restart.

Setup drafts under `/einrichtung` and the sending profile under
`/einstellungen/benachrichtigungen` also edit `config.yaml`.
Saving initially retains the draft. Only the shown, version-related adoption activates
changes; connection and target changes require a current successful diagnosis.
Field names, limits, channel selection and immediate/restart effect:
[Operating instructions 3.0](../archiv/Release-3.0.md#konfigurationsvertrag).

Each info icon explains what the setting changes and what consequences other values have. Hover over it with the mouse, focus it with Tab or tap it on the phone. Escape hides the bubble. Reading does not change any setting.

Next to **Stop Mailhelp** is **Restart Mailhelp**. Both actions have
their own confirmation page. Restarting stops the running service in a controlled manner
and starts the same interpreter with the same options again. Saved settings,
credentials and code are reloaded; setup drafts are not adopted by this.
Open operations are retained. Then open the web interface again.
If a confirmation comes from an earlier start (for example from a page that was opened before a
restart) or is incomplete, Mailhelp states the reason and shows a new confirmation on
the same page.

The following list contains the same help texts as the web interface. Changes are saved only after the separate confirmation. “While running” means adoption at the next safe point; other settings require a restart. Enter numbers with a decimal point, e.g. `0.30`. Use `null`, `disabled` and `unlimited` only where permitted below. For number fields, special values can possibly only be set directly in `config.yaml`.

## Credentials <!-- mailhelp-id:web-einstellungen/zugangsdaten -->

The separate **Credentials** area is reachable via the area overview.
It groups mailboxes, OpenRouter, Telegram and the configured target profiles.
Each entry shows only “present” or “missing” and offers an empty password field
for a new value. Existing values are not displayed even after saving.

“Save access” replaces exclusively the selected key in `.env`;
comments and other keys remain preserved. The values take effect after a restart.
Process variables have priority and are marked separately. For additional
target profiles, an inherited client ID or an inherited client key is displayed;
a value saved there is its own override for this profile.
Saved Microsoft logins are renewed via `mailhelp --microsoft-login`,
Google logins via `mailhelp --google-auth` (for additional profiles with `--profile`).

The forms check session, CSRF, configuration and `.env` version as well as an
idempotency key. An outdated form does not overwrite newer changes.
Interrupted save operations are reconciled on a retry based on the file state. The evidence under `credential-edits.json` contains only key-bound
HMACs and status data; credential values are stored neither in HTML nor in logs or the
command queue. Editing does not trigger external creation.
The interface also works without JavaScript.

**All credentials and new accounts** opens `/einstellungen/zugangsdaten`.
This complete account overview also takes IServ accounts and mailboxes
in the current setup draft into account. Here, new values must be explicitly confirmed;
the forms check the `.env` file state and prevent repeated writes
via value-free evidence under `secret-operations.json`. The diagnostics uses values stored there
immediately. This allows a new account to be checked before its
configuration draft is applied. The HMAC evidence described in the previous paragraph
applies to quick access within the general settings page.

## IServ Accounts <!-- mailhelp-id:web-einstellungen/iserv-konten -->

At `/einstellungen/iserv`, **Check connection and activate account** activates a new account
directly: Only after successful login are account and credentials saved, and retrieval
starts without restart in the next secure email cycle. Alternatively, accounts can be created and changed as a
setup draft.
“Do not process older messages before” accepts `TT.MM.JJJJ [HH:MM]` (e.g. `01.09.2026 07:30`),
`JJJJ-MM-TT` (e.g. `2026-09-01`) or an ISO-8601 timestamp with UTC offset.
A pure date applies from 00:00 in the time zone of the configuration draft;
for `Europe/Berlin`, `01.09.2026` is stored as `2026-09-01T00:00:00+02:00`.
In winter, the corresponding winter time offset applies. An empty field inherits the limit of the
assigned Mailbox. German entries with time apply in the configured time zone.
Invalid dates and ISO timestamps without offset are rejected.
In the draft, credentials are stored separately under **Credentials**. Only after diagnosis and
explicit, version-related adoption is the configuration changed; it takes effect after
a restart.
A version conflict responds with HTTP 409; configuration and draft remain unchanged.
Then re-read the configuration in the setup and check the changes again.

## Evaluation charts <!-- mailhelp-id:web-einstellungen/diagramme-der-auswertung -->

Clicking a chart or its **Enlarge** button opens a large view.
On small screens, the graphic can be scrolled horizontally within the view. **Close**
or Escape ends the view and returns keyboard focus to **Enlarge**.
When hovering over, focusing with Tab, or tapping a bar, the time range or
category, data series, and value with unit are displayed. The details remain readable even when moving
the mouse onto the tooltip; Escape hides them. The data does not change as a result.
Tables and SVG descriptions remain available without JavaScript.

## Account status <!-- mailhelp-id:web-einstellungen/kontenstatus -->

The status page shows under **Configured accounts** all saved IMAP and IServ accounts,
Calendar and Tasks per target profile as well as Telegram. Account number and display name distinguish
the accesses. Deactivated accounts and unused target profiles also remain visible.
After every service start, an account begins with “not yet checked”. A recorded successful
contact shows its time; a failed attempt shows “Error”. The results
of one account do not confirm any other account. Open IMAP folder errors keep the account status
at “Error”, even if another folder was read successfully.

Connection changes that have already been applied show “Restart required” until the service restart;
unconfirmed drafts are not listed. If the saved configuration is temporarily
unreadable or invalid, the page shows the accounts of the running service.
Opening the page starts neither a login nor an external write action. Status changes
update the page automatically; running successful retrievals alone do not constantly reload it.

## Mail retrieval and operation <!-- mailhelp-id:web-einstellungen/mailabruf-und-betrieb -->

| Setting / Key | Effect and values | Application |
| --- | --- | --- |
| Retrieval interval (seconds) (`poll_interval_seconds`) | Interval between mail retrievals: 5–86400 seconds. 60 checks about every minute, 300 about every five minutes. Smaller values detect new Mails earlier, larger ones relieve the mail server. A running pass can delay the next retrieval. | While running |
| Dry run (`test_mode`) | yes (true) activates the dry run: confirmed Calendar and Todoist actions are simulated; test data are stored separately. no (false) activates real write actions after explicit confirmation. The dry run does not prevent all network accesses, such as mail retrieval and AI calls. | After restart |
| Language of the interface (`language`) | Default language of the Web interface: de (Deutsch) or en (English). A browser that has selected a language or prefers English sees that one. The AI prompts, topics and the Statistics of the Mails remain German. The change takes effect after a restart. | After restart |
| Time zone (`timezone`) | Time zone for local date and time specifications, e.g. Europe/Berlin with automatic daylight saving time or UTC without daylight saving time change. Use a valid IANA time zone name. A different zone changes the interpretation of local Event times and their display. | After restart |
| Mails per retrieval pass (`imap.batch_size`) | A retrieval pass accepts at most this many new Mails across all mailboxes: 1–1000; default 25. Larger values process backlogs faster but lengthen a single pass; smaller ones distribute the work over more passes. --max-mails replaces the value for a single run. | After restart |
| Newest Mails first (all mailboxes) (`imap.global_newest_first`) | yes (true) selects the newest Mails per pass across all mailboxes and folders by received time. no (false) processes mailbox by mailbox and folder by folder in the configured order. The setting only determines the order, not which Mails are processed. | After restart |

## Replies <!-- mailhelp-id:web-einstellungen/antworten -->

As of 4.8.5, `drafts.enabled: false` globally locks new drafts and new filings.
Saved drafts in the mailbox remain preserved. Automatic filing additionally requires
`smart_reply: true` and `auto_draft: true`; both remain off by default.
`drafts.enabled`, `drafts.folder` and `auto_draft` are applied without restart.
The folder is an IMAP folder name or `null` for the previous mailbox default.
`auto_draft` can also be overridden under Mailboxes → Replies.

| Setting / Key | Effect and Values | Application |
| --- | --- | --- |
| Allow reply drafts (`drafts.enabled`) | Global switch for manual and automatic reply drafts, default on. false prevents new drafts and new filings. Drafts already filed in the mailbox remain preserved. smart_reply and auto_draft keep their own settings. | At runtime |
| Override draft folder (null: mailbox default) (`drafts.folder`) | Optional IMAP draft folder for all mailboxes. null uses their drafts_folder. If the preferred folder is missing, Mailhelp searches for the SPECIAL-USE flag or usual draft folder names. No folders are created. Applies to future filings without restart. | At runtime |
| Automatically file reply drafts in the mailbox (`auto_draft`) | yes (true) automatically files a draft when a written reply need is detected; requires smart_reply and drafts.enabled. Default off. Mailhelp never sends on its own. Overridable per mailbox; is applied at the next safe processing point. | At runtime |
| Personal details for replies (`personal_info`) | Up to 2000 characters, e.g. name, role, signature or desired salutation. The AI model receives these details when creating a reply draft. Empty means no personal additional details. More context can change the tone and content of the draft; the details are not used for email analysis. | At runtime |
| Offer reply drafts (`smart_reply`) | yes (true) offers AI reply drafts; requires drafts.enabled and the draft_reply stage in prompts.yaml. Without auto_draft, a draft is filed only after explicit saving in the draft folder. Mailhelp never sends on its own. Mailboxes can override the value individually. | After restart |

## Targets <!-- mailhelp-id:web-einstellungen/ziele -->

| Setting / Key | Effect and values | Takes effect |
| --- | --- | --- |
| Task service (`targets.task_provider`) | Service for new task proposals: todoist, microsoft_todo (Microsoft To Do), caldav (task list with VTODO, e.g. Nextcloud Tasks) apple_reminders (iCloud Reminders via CalDAV; lists updated to the new iCloud Reminders are not reachable there) google_tasks (Google Tasks; only adopts the date, an exact deadline is in the text; sign-in with Google Tasks permission required) or notion (pages in a Notion data source; beforehand under target profiles assign data source and properties, token NOTION_TOKEN). The change takes effect after a restart. First enter the matching target, then switch the service. | After restart |
| CalDAV task list (address) (`targets.caldav_task_url`) | Full https address of the CalDAV task list (VTODO), e.g. https://cloud.example.org/remote.php/dav/calendars/anna/tasks/. For Apple Reminders, an address under https://caldav.icloud.com. Existing entries are not moved. Creation still requires your explicit confirmation. | After restart |
| CalDAV calendar (address) (`targets.caldav_calendar_url`) | Full https address of the CalDAV calendar collection, e.g. https://cloud.example.org/remote.php/dav/calendars/anna/personal/. Only required for calendar service caldav; sign-in with CALDAV_USERNAME and app password CALDAV_PASSWORD. Existing entries are not moved. Creation still requires your explicit confirmation. | After restart |
| Deadline for removal (`targets.removal_window_minutes`) | Time window in minutes after creating an entry in which it can be removed again via the web interface or Telegram: 1–1440; default 10. After the deadline expires, the entry is no longer deleted by Mailhelp. | After restart |
| Google Calendar (`targets.google_calendar`) | ID of the target calendar for new event proposals. primary denotes the main calendar; a concrete calendar ID selects another accessible calendar. Existing events are not moved. Not empty, at most 500 characters. Creation still requires your explicit confirmation. | After restart |
| Calendar service (`targets.calendar_provider`) | Service for new event proposals: google (Google Calendar), caldav (e.g. Nextcloud, iCloud, mailbox.org) or outlook (Outlook / Microsoft 365). The change takes effect after a restart; proposals already confirmed for the previous target are not written to the new one. First enter the matching target, then switch the service. Enter credentials under Settings → Credentials or in the .env file. | After restart |
| Microsoft tenant (`targets.microsoft_tenant`) | Microsoft tenant for sign-in: common (personal and work accounts), consumers, organizations or the tenant ID. Applies to Outlook calendar and Microsoft To Do. | After restart |
| Google Tasks list (`targets.google_tasks_list`) | ID of the Google Tasks list or @default for the first list of the account. Only required for task service google_tasks. Google Tasks stores only the date of a task; an exact deadline with time is in the text. Remove again is not available for Google Tasks. Creation still requires your explicit confirmation. | After restart |
| Microsoft To Do list (`targets.microsoft_todo_list`) | ID of the Microsoft To Do list or default for the default list "Tasks". Only required for task service microsoft_todo. Existing entries are not moved. Creation still requires your explicit confirmation. | After restart |
| Outlook calendar (`targets.outlook_calendar`) | ID of the Outlook calendar or default for the default calendar of the signed-in Microsoft account. Only required for calendar service outlook. Existing entries are not moved. Creation still requires your explicit confirmation. | After restart |
| Todoist project (`targets.todoist_project`) | ID of the Todoist project for new task proposals, not its display name. A different ID directs new proposals into a different project; existing tasks are not moved. Not empty, at most 500 characters. Creation still requires your explicit confirmation. | After restart |

## Call budget and email limits <!-- mailhelp-id:web-einstellungen/aufrufbudget-und-mailgrenzen -->

| Setting / key | Effect and values | Takes effect |
| --- | --- | --- |
| AI calls per minute (`limits.llm_calls_per_minute`) | Budget of 1–600 AI calls per minute. A smaller value slows processing and reduces load peaks; a larger value allows more calls, insofar as the provider and other limits permit. This is not a fixed monetary or daily cost limit. | After restart |
| Maximum AI request size (bytes) (`limits.max_llm_payload_bytes`) | Size limit for prepared email data sent to the AI: 1–100000000 bytes, not a token count; default 500000. Larger values allow more content and can increase costs and runtime. Prepared content that is too large is rejected; a smaller value is not an automatic summary. | After restart |
| Maximum email size (bytes) (`limits.max_mail_bytes`) | Size limit for the message text without attachments: 1024–100000000 bytes. Attachments have their own limit for text extraction. | After restart |
| Text recognition: maximum attachment size (bytes) (`limits.max_attachment_bytes`) | Maximum size per attachment for local text extraction and OCR: 1024–100000000 bytes; default 5000000 bytes (5 MB). Larger attachments are not evaluated. The message always receives a suggestion for manual review; further messages continue to be retrieved. | After restart |

## Time limits and retries <!-- mailhelp-id:web-einstellungen/zeitlimits-und-wiederholungen -->

| Setting / key | Effect and values | Application |
| --- | --- | --- |
| Understanding replies: attempts (`retries.interpretation_attempts`) | Total number of attempts when understanding a Telegram reply: 1–20, including the first attempt. 1 allows no retry; 3 allows up to three attempts. Higher values can absorb temporary AI errors, but lengthen processing and can cause more AI calls. | After restart |
| Understanding replies: wait time (s) (`retries.interpretation_backoff_seconds`) | Wait time before a retry when understanding a Telegram reply: 1–86400 seconds. 60 means one minute, 300 five minutes. Larger values give the service more recovery time and delay continuation. If only one attempt is allowed, no retry occurs. | After restart |
| CalDAV: initial wait time (s) (`timeouts.caldav.initial_backoff_seconds`) | CalDAV: First wait time before a retry: 0–30 seconds. 0 does not wait initially; larger values give the service more recovery time. Further wait times increase up to the longest wait time. Without retries, this value has no effect. | After restart |
| CalDAV: longest wait time (s) (`timeouts.caldav.max_backoff_seconds`) | CalDAV: Upper limit of the wait time between retries: 0–60 seconds and at least as large as the initial wait time. Larger values allow longer pauses, smaller ones limit the delay. Without retries, this value has no effect. | After restart |
| CalDAV: retries (`timeouts.caldav.retries`) | CalDAV: Additional retries for retryable service errors: 0–10. 0 means only the first attempt, 2 allows up to three attempts in total. More retries can bridge temporary errors, but increase runtime and possibly costs. Unclear external write results are reconciled before a new creation. | After restart |
| CalDAV: time limit (s) (`timeouts.caldav.timeout_seconds`) | CalDAV: Time limit of a call attempt: 1–300 seconds. Small values detect non-responding services faster, but can abort slow responses. Large values give the service more time and lengthen possible wait times. | After restart |
| Google Calendar: initial wait time (s) (`timeouts.google_calendar.initial_backoff_seconds`) | Google Calendar: First wait time before a retry: 0–30 seconds. 0 does not wait initially; larger values give the service more recovery time. Further wait times increase up to the longest wait time. Without retries, this value has no effect. | After restart |
| Google Calendar: longest wait time (s) (`timeouts.google_calendar.max_backoff_seconds`) | Google Calendar: Upper limit of the wait time between retries: 0–60 seconds and at least as large as the initial wait time. Larger values allow longer pauses, smaller ones limit the delay. Without retries, this value has no effect. | After restart |
| Google Calendar: retries (`timeouts.google_calendar.retries`) | Google Calendar: Additional retries for retryable service errors: 0–10. 0 means only the first attempt, 2 allows up to three attempts in total. More retries can bridge temporary errors, but increase runtime and possibly costs. Unclear external write results are reconciled before a new creation. | After restart |
| Google Calendar: time limit (s) (`timeouts.google_calendar.timeout_seconds`) | Google Calendar: Time limit of a call attempt: 1–300 seconds. Small values detect non-responding services faster, but can abort slow responses. Large values give the service more time and lengthen possible wait times. | After restart |
| IMAP: initial wait time (s) (`timeouts.imap.initial_backoff_seconds`) | IMAP: First wait time before a retry: 0–30 seconds. 0 does not wait initially; larger values give the service more recovery time. Further wait times increase up to the longest wait time. Without retries, this value has no effect. | After restart |
| IMAP: longest wait time (s) (`timeouts.imap.max_backoff_seconds`) | IMAP: Upper limit of the wait time between retries: 0–60 seconds and at least as large as the initial wait time. Larger values allow longer pauses, smaller ones limit the delay. Without retries, this value has no effect. | After restart |
| IMAP: retries (`timeouts.imap.retries`) | IMAP: Additional retries for retryable service errors: 0–10. 0 means only the first attempt, 2 allows up to three attempts in total. More retries can bridge temporary errors, but increase runtime and possibly costs. Unclear external write results are reconciled before a new creation. | After restart |
| IMAP: time limit (s) (`timeouts.imap.timeout_seconds`) | IMAP: Time limit of a call attempt: 1–300 seconds. Small values detect non-responding services faster, but can abort slow responses. Large values give the service more time and lengthen possible wait times. | After restart |
| Microsoft 365: initial wait time (s) (`timeouts.microsoft.initial_backoff_seconds`) | Microsoft 365: First wait time before a retry: 0–30 seconds. 0 does not wait initially; larger values give the service more recovery time. Further wait times increase up to the longest wait time. Without retries, this value has no effect. | After restart |

## Time limits and retries <!-- mailhelp-id:web-einstellungen/zeitlimits-und-wiederholungen-2 -->

| Microsoft 365: Longest wait time (s) (`timeouts.microsoft.max_backoff_seconds`) | Microsoft 365: Upper limit of the wait time between retry attempts: 0–60 seconds and at least as large as the initial wait time. Larger values allow longer pauses, smaller ones limit the delay. Without retries, this value has no effect. | After restart |
| Microsoft 365: Retries (`timeouts.microsoft.retries`) | Microsoft 365: Additional retries for retryable service errors: 0–10. 0 means only the first attempt, 2 allows up to three attempts in total. More retries can bridge temporary errors but increase runtime and possibly costs. Unclear external write results are reconciled before a new creation. | After restart |
| Microsoft 365: Time limit (s) (`timeouts.microsoft.timeout_seconds`) | Microsoft 365: Time limit of a call attempt: 1–300 seconds. Small values detect non-responding services faster but can abort slow responses. Large values give the service more time and extend possible wait times. | After restart |
| Google Tasks: Initial wait time (s) (`timeouts.google_tasks.initial_backoff_seconds`) | Google Tasks: Initial wait time before a retry attempt: 0–30 seconds. 0 does not wait initially; larger values give the service more recovery time. Further wait times increase up to the longest wait time. Without retries, this value has no effect. | After restart |
| Google Tasks: Longest wait time (s) (`timeouts.google_tasks.max_backoff_seconds`) | Google Tasks: Upper limit of the wait time between retry attempts: 0–60 seconds and at least as large as the initial wait time. Larger values allow longer pauses, smaller ones limit the delay. Without retries, this value has no effect. | After restart |
| Google Tasks: Retries (`timeouts.google_tasks.retries`) | Google Tasks: Additional retries for retryable service errors: 0–10. 0 means only the first attempt, 2 allows up to three attempts in total. More retries can bridge temporary errors but increase runtime and possibly costs. Unclear external write results are reconciled before a new creation. | After restart |
| Google Tasks: Time limit (s) (`timeouts.google_tasks.timeout_seconds`) | Google Tasks: Time limit of a call attempt: 1–300 seconds. Small values detect non-responding services faster but can abort slow responses. Large values give the service more time and extend possible wait times. | After restart |
| Notion: Initial wait time (s) (`timeouts.notion.initial_backoff_seconds`) | Notion: Initial wait time before a retry attempt: 0–30 seconds. 0 does not wait initially; larger values give the service more recovery time. Further wait times increase up to the longest wait time. Without retries, this value has no effect. | After restart |
| Notion: Longest wait time (s) (`timeouts.notion.max_backoff_seconds`) | Notion: Upper limit of the wait time between retry attempts: 0–60 seconds and at least as large as the initial wait time. Larger values allow longer pauses, smaller ones limit the delay. Without retries, this value has no effect. | After restart |
| Notion: Retries (`timeouts.notion.retries`) | Notion: Additional retries for retryable service errors: 0–10. 0 means only the first attempt, 2 allows up to three attempts in total. More retries can bridge temporary errors but increase runtime and possibly costs. Unclear external write results are reconciled before a new creation. | After restart |
| Notion: Time limit (s) (`timeouts.notion.timeout_seconds`) | Notion: Time limit of a call attempt: 1–300 seconds. Small values detect non-responding services faster but can abort slow responses. Large values give the service more time and extend possible wait times. | After restart |
| Ollama: Initial wait time (s) (`timeouts.ollama.initial_backoff_seconds`) | Ollama: Initial wait time before a retry attempt: 0–30 seconds. 0 does not wait initially; larger values give the service more recovery time. Further wait times increase up to the longest wait time. Without retries, this value has no effect. | After restart |
| Ollama: Longest wait time (s) (`timeouts.ollama.max_backoff_seconds`) | Ollama: Upper limit of the wait time between retry attempts: 0–60 seconds and at least as large as the initial wait time. Larger values allow longer pauses, smaller ones limit the delay. Without retries, this value has no effect. | After restart |
| Ollama: Retries (`timeouts.ollama.retries`) | Ollama: Additional retries for retryable service errors: 0–10. 0 means only the first attempt, 2 allows up to three attempts in total. More retries can bridge temporary errors but increase runtime and possibly costs. Unclear external write results are reconciled before a new creation. | After restart |
| Ollama: Time limit (s) (`timeouts.ollama.timeout_seconds`) | Ollama: Time limit of a call attempt: 1–1800 seconds. Small values detect non-responding services faster but can abort slow responses. Large values give the service more time and extend possible wait times. | After restart |
| OpenRouter: Initial wait time (s) (`timeouts.openrouter.initial_backoff_seconds`) | OpenRouter: Initial wait time before a retry attempt: 0–30 seconds. 0 does not wait initially; larger values give the service more recovery time. Further wait times increase up to the longest wait time. Without retries, this value has no effect. | After restart |

## Time limits and retries <!-- mailhelp-id:web-einstellungen/zeitlimits-und-wiederholungen-3 -->

| OpenRouter: longest wait time (s) (`timeouts.openrouter.max_backoff_seconds`) | OpenRouter: upper limit of the wait time between retries: 0–60 seconds and at least as large as the initial wait time. Larger values allow longer pauses, smaller ones limit the delay. Without retries, this value has no effect. | After restart |
| OpenRouter: retries (`timeouts.openrouter.retries`) | OpenRouter: additional retries for retryable service errors: 0–10. 0 means only the first attempt, 2 allows up to three attempts in total. More retries can bridge temporary errors, but increase runtime and possibly costs. Unclear external write results are reconciled before a new creation. | After restart |
| OpenRouter: timeout (s) (`timeouts.openrouter.timeout_seconds`) | OpenRouter: timeout of a call attempt: 1–300 seconds. Small values detect non-responding services faster, but can abort slow responses. Large values give the service more time and extend possible wait times. | After restart |
| Telegram: initial wait time (s) (`timeouts.telegram.initial_backoff_seconds`) | Telegram: initial wait time before a retry: 0–30 seconds. 0 initially does not wait; larger values give the service more recovery time. Further wait times increase up to the longest wait time. Without retries, this value has no effect. | After restart |
| Telegram: longest wait time (s) (`timeouts.telegram.max_backoff_seconds`) | Telegram: upper limit of the wait time between retries: 0–60 seconds and at least as large as the initial wait time. Larger values allow longer pauses, smaller ones limit the delay. Without retries, this value has no effect. | After restart |
| Telegram: retries (`timeouts.telegram.retries`) | Telegram: additional retries for retryable service errors: 0–10. 0 means only the first attempt, 2 allows up to three attempts in total. More retries can bridge temporary errors, but increase runtime and possibly costs. Unclear external write results are reconciled before a new creation. | After restart |
| Telegram: timeout (s) (`timeouts.telegram.timeout_seconds`) | Telegram: timeout of a call attempt: 1–300 seconds. Small values detect non-responding services faster, but can abort slow responses. Large values give the service more time and extend possible wait times. | After restart |
| Todoist: initial wait time (s) (`timeouts.todoist.initial_backoff_seconds`) | Todoist: initial wait time before a retry: 0–30 seconds. 0 initially does not wait; larger values give the service more recovery time. Further wait times increase up to the longest wait time. Without retries, this value has no effect. | After restart |
| Todoist: longest wait time (s) (`timeouts.todoist.max_backoff_seconds`) | Todoist: upper limit of the wait time between retries: 0–60 seconds and at least as large as the initial wait time. Larger values allow longer pauses, smaller ones limit the delay. Without retries, this value has no effect. | After restart |
| Todoist: retries (`timeouts.todoist.retries`) | Todoist: additional retries for retryable service errors: 0–10. 0 means only the first attempt, 2 allows up to three attempts in total. More retries can bridge temporary errors, but increase runtime and possibly costs. Unclear external write results are reconciled before a new creation. | After restart |
| Todoist: timeout (s) (`timeouts.todoist.timeout_seconds`) | Todoist: timeout of a call attempt: 1–300 seconds. Small values detect non-responding services faster, but can abort slow responses. Large values give the service more time and extend possible wait times. | After restart |
| Revision: attempts (`retries.revision_attempts`) | Total number of attempts when revising a suggestion: 1–20, including the first attempt. 1 allows no retry; 3 allows up to three attempts. Higher values can catch transient AI errors, but extend processing and can cause more AI calls. | After restart |
| Revision: wait time (s) (`retries.revision_backoff_seconds`) | Wait time before a retry when revising a suggestion: 1–86400 seconds. 60 means one minute, 300 five minutes. Larger values give the service more recovery time and delay continuation. If only one attempt is allowed, no retry occurs. | After restart |

## Original attachments <!-- mailhelp-id:web-einstellungen/originalanhaenge -->

| Setting / Key | Effect and values | Application |
| --- | --- | --- |
| Maximum size per file (bytes) (`attachments.max_original_bytes`) | Largest file that is stored as original: 1024–104857600 bytes (default 26214400 bytes = 25 MiB). Larger attachments remain only in the Mailbox. | After restart |
| Maximum size per Email (bytes) (`attachments.max_total_bytes`) | At most this many bytes of originals per Email: 1024–524288000 (default 50 MB). Further attachments of the same Email are not stored. | After restart |
| Store originals (`attachments.store_originals`) | yes (true) stores original documents (PDF, Word, Excel, OpenDocument, Text, Images) of newly processed Mails for download in the Web interface. no (false) stores only image previews. Stored originals are deleted with the retention period for Email contents. | After restart |

## Retention <!-- mailhelp-id:web-einstellungen/aufbewahrung -->

| Setting / Key | Effect and Values | Application |
| --- | --- | --- |
| Retain analyses (days) (`retention.analysis_days`) | Retention of archived analyses. null takes over the deadline for AI diagnostic data (debug_llm_days). 1–3650 means full days since the last update of the completed process. Smaller values remove content earlier. disabled removes them on the next cleanup run, unlimited preserves them without a deadline. Open processes remain protected. Removed content cannot be restored by later extending the deadline. | At runtime |
| Retain AI diagnostic data (days) (`retention.debug_llm_days`) | Retention of AI diagnostic data in the process, such as summary and validation errors; separate JSONL log files have their own deadlines. 1–3650 means full days since the last update of the completed process. Smaller values remove content earlier. disabled removes them on the next cleanup run, unlimited preserves them without a deadline. Open processes remain protected. Removed content cannot be restored by later extending the deadline. | At runtime |
| Retain Email texts (days) (`retention.full_mail_days`) | Retention of stored Email texts, image previews and local draft texts; the original Email in the Mailbox is not deleted. Default 30 days. 1–3650 means full days since the last update of the completed process. Smaller values remove content earlier. disabled removes them on the next cleanup run, unlimited preserves them without a deadline. Open processes remain protected. Removed content cannot be restored by later extending the deadline. | At runtime |
| Retain history (days) (`retention.history_days`) | Retention of the process history and the contents of historical proposal versions; identifiers for protection against duplicate creation remain preserved. Default 90 days. 1–3650 means full days since the last update of the completed process. Smaller values remove content earlier. disabled removes them on the next cleanup run, unlimited preserves them without a deadline. Open processes remain protected. Removed content cannot be restored by later extending the deadline. | At runtime |
| Retain activity reports (days) (`retention.activity_report_days`) | Retention of stored activity reports and their exports; the Mailbox remains unchanged. 1–3650 means full days since the last update of the completed process. Smaller values remove content earlier. disabled removes them on the next cleanup run, unlimited preserves them without a deadline. Open processes remain protected. Removed content cannot be restored by later extending the deadline. | At runtime |
| Retain decision learning data (days) (`retention.decision_learning_days`) | Retention of the learning data of manual decisions (Email, AI results, proposal before and after): 1–3650 means full days since the decision. unlimited (default) preserves without a deadline, disabled no longer records anything and empties the data on the next cleanup run. Removed records cannot be restored. | At runtime |
| Cleanup every (minutes) (`retention.cleanup_interval_minutes`) | Interval of retention cleanup in minutes: 0–1440; default 60. The cleanup runs in the processing flow and briefly pauses Email retrieval and web actions during it. 0 cleans up on every retrieval cycle; larger values remove expired content correspondingly later. | At runtime |

## Logging <!-- mailhelp-id:web-einstellungen/protokollierung -->

| Setting / Key | Effect and values | Applied |
| --- | --- | --- |
| Console: Minimum level (`logging.console.level`) | Minimum level of console messages: DEBUG also shows diagnostic information, INFO normal operation, WARNING only warnings and more severe messages, ERROR errors, and CRITICAL only the most severe errors. Higher levels reduce output and make troubleshooting more difficult. Content logs are controlled separately. | After restart |
| Log file: Minimum level (`logging.file.level`) | Minimum level of the general log file: DEBUG contains diagnostic information, INFO normal operation, WARNING warnings and more severe messages, ERROR errors, and CRITICAL only the most severe errors. Higher levels reduce the amount of data. Separate AI content logs are not enabled or disabled by this. | After restart |
| Log AI requests in full (`logging.llm.include_requests`) | yes (true) allows full AI requests in the separate AI log, provided it is enabled. This can store prompts and private email content and requires more storage. no (false) omits the full request contents. Logs already written are not deleted by this. | After restart |
| Log AI responses in full (`logging.llm.include_responses`) | yes (true) allows full AI responses in the separate AI log, provided it is enabled. This helps with troubleshooting but can store private content. no (false) omits full response contents. Logs already written are not deleted by this. | After restart |
| Verbose log (`logging.verbose`) | Verbose log: record all routine requests and repeated errors. Default off; unchanged folder counts appear once per hour and repeated errors every 15 minutes. Full AI contents remain separately enableable. | After restart |
| Enable console output (`logging.console.enabled`) | yes (true) writes messages to the terminal or container log. no (false) suppresses console output; the log file is unaffected. | After restart |
| Enable log file (`logging.file.enabled`) | yes (true) writes the general log file in the log directory. no (false) does not write a general log file; this makes troubleshooting more difficult. | After restart |
| Enable AI log (`logging.llm.enabled`) | yes (true) writes the separate AI log with call metadata; full contents only if requests or responses are additionally allowed. no (false) does not write an AI log. | After restart |
| AI log: Minimum level (`logging.llm.level`) | Minimum level of the AI log: DEBUG contains diagnostic information, INFO normal operation, WARNING warnings and more severe messages, ERROR errors, and CRITICAL only the most severe errors. Higher levels reduce the amount of data. | After restart |
| Enable Telegram log (`logging.telegram.enabled`) | yes (true) writes a separate audit log of Telegram messages including contents. no (false) omits this; deliveries remain visible in the general log without contents. | After restart |
| Telegram log: Minimum level (`logging.telegram.level`) | Minimum level of the Telegram log: DEBUG contains diagnostic information, INFO normal operation, WARNING warnings and more severe messages, ERROR errors, and CRITICAL only the most severe errors. | After restart |

## Costs and Measurement <!-- mailhelp-id:web-einstellungen/kosten-und-messung -->

| Setting / Key | Effect and Values | Application |
| --- | --- | --- |
| Electricity price (EUR/kWh) (`metrics.electricity_eur_per_kwh`) | Electricity price for local AI cost estimates: 0–100 EUR/kWh. 0.30 means 30 cents per kWh. A higher price increases the estimate proportionally; 0 results in no estimated electricity costs. The value affects neither cloud prices nor electricity consumption. | While running |
| Enable metric collection (`metrics.enabled`) | yes (true) records measurements for AI calls, runtimes, and costs without email contents. no (false) stops new measurements; already recorded values remain until cleanup. This setting disables neither AI calls nor general logs. | While running |
| Exchange rate as of (`metrics.exchange_rate_date`) | Reference date of the manually maintained exchange rate in format YYYY-MM-DD, e.g. 2026-10-12. null leaves the date open. It indicates the recency of the rate and does not change the conversion factor. A date is only allowed with an exchange rate set. | While running |
| Ollama power (watts) (`metrics.ollama_power_watts`) | Assumed power consumption during local AI calls: 0–100000 watts. 300 stands for 300 W; double power results in double estimated electricity costs for the same duration. 0 results in no estimated electricity costs. This does not measure or limit actual hardware power. | While running |
| Retain individual measurements (days) (`metrics.retention_days`) | Retention of individual measurements: 1–3650 days. 30 retains approximately one month, 90 approximately three months. Shorter deadlines save storage but restrict retrospective statistics. Older measurements are cleaned up; disabled and unlimited are not allowed here. | While running |
| Exchange rate (USD per EUR) (`metrics.usd_per_eur`) | US dollars per euro, greater than 0: At 1.1, 11 USD is displayed as 10 EUR. A higher rate results in fewer euros for the same dollar amount. null disables euro conversion; then the exchange rate date must also be null. The rate is maintained manually, not retrieved automatically. | While running |

## Telegram <!-- mailhelp-id:web-einstellungen/telegram -->

| Setting / Key | Effect and values | Applied |
| --- | --- | --- |
| Telegram: authorized user ID (`telegram.user_id`) | Numeric Telegram ID of the only account whose inputs Mailhelp accepts; greater than 0. Messages from other accounts are ignored. An incorrect ID blocks operation via Telegram; the Web interface remains usable. | After restart |
| Telegram: chat for messages (`telegram.chat_id`) | Numeric ID of the chat that Mailhelp writes to; in a private chat usually the same as the user ID. An incorrect ID leads to delivery errors; diagnostics and --check-access report them and name found chats. | After restart |
| Telegram: decisions one after another (`telegram.sequential_questions`) | yes (true) shows only the current decision with buttons at a time; further ones follow one after another. no (false) sends all open Proposals immediately. One after another prevents confused answers when many questions are open at the same time. | After restart |

## Image analysis <!-- mailhelp-id:web-einstellungen/bildauswertung -->

| Setting / Key | Effect and values | Takes effect |
| --- | --- | --- |
| Analyze image attachments and scans (`vision.enabled`) | yes (true) lets image attachments and scanned PDFs be read by the AI model (stage vision_ocr in prompts.yaml), so that events and tasks in them are recognized; the images are transferred for this and cause costs. no (false) analyzes only text. | After restart |
| Image analysis: Images per email (`vision.max_images_per_mail`) | At most this many images per email are analyzed: 1–10; default 3. More images capture extensive scans more completely and increase costs and runtime. | After restart |
| Image analysis: Maximum size per image (bytes) (`vision.max_image_bytes`) | Additional size limit for image analysis: 10240–50000000 bytes; default 5000000 (5 MB). The text recognition limit limits.max_attachment_bytes applies additionally; if it is exceeded, a manual review task is created. | After restart |
| Image analysis: Longest edge (pixels) (`vision.max_edge_pixels`) | Images are scaled down to this longest edge before transfer: 512–4096 pixels; default 1600. Larger values preserve fine text better and increase data volume and costs. | After restart |

## Daily overview <!-- mailhelp-id:web-einstellungen/tagesueberblick -->

| Setting / Key | Effect and values | Application |
| --- | --- | --- |
| Daily overview: Events (`daily_briefing.include_calendar`) | yes (true) includes today's events from the target calendar in the daily overview. no (false) omits them. Only effective when the daily overview is enabled. | After restart |
| Daily overview: Tasks (`daily_briefing.include_tasks`) | yes (true) includes due tasks from the task list in the daily overview. no (false) omits them. Only effective when the daily overview is enabled. | After restart |
| Daily overview: open decisions (`daily_briefing.include_open`) | yes (true) mentions the open proposals and queries in the daily overview. no (false) omits them. Only effective when the daily overview is enabled. | After restart |

## Activity Reports <!-- mailhelp-id:web-einstellungen/taetigkeitsberichte -->

| Setting / Key | Effect and values | Applied |
| --- | --- | --- |
| Enable activity reports (`activity_report.enabled`) | yes (true) allows activity reports in the Web interface: a pure read-only pass through a mailbox on a topic with XLSX export; requires the stages activity_relevance and activity_events in prompts.yaml. no (false) hides the function. | After restart |
| Activity report: at most Mails (`activity_report.max_mails`) | A report pauses after this many read Mails: 1–20000; default 2000. Larger values cover longer time periods and increase runtime and AI costs. | After restart |
| Activity report: at most AI calls (`activity_report.max_llm_calls`) | A report pauses after this many AI calls: 1–50000; default 3000. The limit protects against unexpectedly high costs; a paused report can be continued. | After restart |
| Activity report: share of AI budget (`activity_report.max_share_of_llm_budget`) | Share of limits.llm_calls_per_minute that a running report may use: greater than 0 to 1; default 0.5. Smaller values leave normal Mail processing more leeway and slow down the report. | After restart |
| Activity report: characters per full text (`activity_report.max_fulltext_chars`) | Full texts in the export are truncated to this many characters: 1000–32000; default 30000, matching Excel's cell limit. | After restart |
| Activity report: export Mails without Events (`activity_report.export_mails_without_events`) | yes (true) also exports relevant Mails without recognized Events. no (false) exports only Mails with recognized Events. | After restart |

## Learning mode <!-- mailhelp-id:web-einstellungen/lernmodus -->

| Setting / Key | Effect and values | Application |
| --- | --- | --- |
| Learning mode: parallel AI calls (`learning.parallel_llm_calls`) | Concurrent AI calls in learning mode (--learn): 1–100; default 4. More parallel calls speed up learning and increase load peaks; the per-minute budget limits.llm_calls_per_minute still applies. | After restart |
| Learning dataset: take over complete AI content (`learning.decision_llm_content`) | yes (true) takes over complete AI requests and responses from the AI log into every record of the decision learning dataset; they are only present if the AI log logs this content. no (false, default) stores only the call IDs. | After restart |
| Enable sender hints (`learning.sender_hints_enabled`) | yes (true, default) displays hints about senders with conspicuously many rejections. no (false) turns sender hints off completely. | At runtime |
| Sender hints: evaluation period in days (`learning.sender_hint_days`) | Considered time range for a sender's acceptance rate: 1–365 days; default 90. Older decisions are not used for sender hints. | At runtime |
| Sender hints: minimum number of proposals (`learning.sender_hint_min_proposals`) | Minimum number of decided proposals from a sender before a hint appears: 1–100; default 5. | At runtime |
| Sender hints: maximum acceptance rate (`learning.sender_hint_max_acceptance_rate`) | Highest acceptance rate up to which a hint is generated: 0.0–1.0 (0 % to 100 %); default 0.1 (10 %). | At runtime |
| Enable rule learning run hint (`learning.learning_run_hints_enabled`) | yes (true, default) shows a hint on “Open” and “Learning” when many new rejections are present since the last learning run. no (false) turns this hint off. | At runtime |
| Rule learning run hint: rejection threshold (`learning.learning_run_hint_rejections`) | Number of new rejections since the last rule learning run from which a hint is displayed: 1–500; default 20. | At runtime |
| Enable suggested prefilter rules (`learning.prefilter_hints_enabled`) | yes (true, default) shows under Learning → Proposals hints for ignore and VIP rules from stored decisions. no (false) turns them off. | At runtime |
| Suggested prefilter rules: time range in days (`learning.prefilter_hint_days`) | Considered mails from the last 1–365 days; default 30. | At runtime |
| Suggested prefilter rules: minimum number of irrelevant mails (`learning.prefilter_hint_irrelevant_mails`) | This many mails from a sender, all classified by the AI as irrelevant and without a contrary response, produce an “ignore” hint: 2–100; default 3. | At runtime |
| Suggested prefilter rules: minimum number of confirmed mails (`learning.prefilter_hint_vip_mails`) | This many mails from a sender, all of which led to at least one confirmed proposal, produce a “VIP” hint: 2–100; default 5. | At runtime |

## Web interface <!-- mailhelp-id:web-einstellungen/weboberflaeche -->

| Setting / Key | Effect and values | Application |
| --- | --- | --- |
| Web: Session duration (days) (`web.session_days`) | A paired device remains signed in for this long before it must be paired again: 1–365 days; default 30. Shorter values reduce the risk of lost devices, longer ones save pairings. | After restart |
| Web: Access in own network (`web.lan_access`) | yes (true) makes the web interface reachable in the own WLAN at the PC's private IP address (unencrypted HTTP); requires web.host 0.0.0.0, otherwise the change is rejected. no (false) restricts access to this PC and the allowed addresses. | After restart |

## Help chat <!-- mailhelp-id:web-einstellungen/hilfschat -->

From 5.4.1, **Clear chat** also removes question texts and field references from stored jobs.
Only content-free job identifiers, Status and hashes remain to prevent duplicate transmission.
Previously cleared legacy data is cleaned up on the next start. A disabled help chat
starts no further model call even for queued questions and retries.

Search also finds file and configuration settings, such as `web.port` and
`reanalysis.max_jobs_per_day`. Such hits name the operating path and open the matching
bundled documentation; they offer no web form for editing a file value.

**Help on Settings** answers questions about the meaning of settings and about
operating procedures. On all settings pages, the round chat icon at the bottom right (on
mobile above the bottom bar) opens the chat. “Ask about this” on a setting or a hit
in instant search opens the same small window with this reference. The settings page remains
operable. Search, section switching, editing, confirming and saving do not close the window.
Old `/hilfe` links open it on the settings overview. Every question is explicitly submitted with **Send question**; typing,
searching and help texts never trigger an AI call.

- **Sources:** Mailhelp selects at most six matching sections of the bundled
documentation and sends them with the question and the short History (at most ten questions)
via the active AI connection (Stage `settings_help`, same model as `action_router`).
In the window, a short answer appears first in one to two sentences; **Show detailed answer**
expands the full instructions. Both versions are generated in the same AI call.
The AI writes them as Markdown; the window displays numbered steps, lists,
**bold**, `Code` and subheadings formatted. HTML, images and links from the
answer are never adopted; the checked sources are listed below.
Under each answer, the used sections and settings are listed as links; without matching
sections, Mailhelp answers itself, without an AI call, and asks for a more precise question.
- **Limits:** The chat changes nothing – no settings, accounts, calendars or messages.
Even for the request “Change this for me”, it only gives instructions.
- **Privacy and costs:** Question, History and documentation excerpts go to the
AI provider and cause costs like other queries, even in test mode. Known
credentials from `.env` are removed beforehand; do not type passwords or tokens.
Current setting values are never sent. In the window, this notice is
collapsed under **Subject to charges**; a click or the Enter key expands it.
- **Retention:** The History belongs to the session and is deleted on logout, revocation or after
24 hours without activity; **Clear chat** deletes it immediately. Logs contain
questions and answers only when content logging is enabled.
- **Operating the window:** Drag the header to move the window, and drag an edge or
corner to resize it (at least 280 × 180 pixels, at most up to the
screen edge). Using the keyboard, focus the title “Help on Settings”: arrow keys
move, Shift+arrow keys resize. The browser tab remembers the size. **Close help chat** hides it without deleting History or draft.
**Clear chat** discards both and keeps the window open. Clicking outside and Escape
do not close it. Sources can be read in the window; **Back to conversation** returns.
- **Draft and position:** In JavaScript mode, the current browser tab remembers the
State, the reading position in the conversation and the unsent question in `sessionStorage`, limited to the session and at most
24 hours. Do not enter tokens; this is not a secret store. The conversation History remains
bound to the session on the server side. Two tabs have their own windows and drafts, but the same
History. On logout or invalid session, the local copy is removed.
- **Without browser storage/JavaScript:** A server-side State keeps the open window.
Without JavaScript, an unsent question is not retained on a page change; a new
answer appears on the next page load or reload. The window cannot then be
moved; if it covers a button, submit the search field with the Enter key or
close the window. The settings page is not automatically reloaded because of a chat answer.
If browser storage is blocked, JavaScript saves the draft before navigation;
if saving fails, the current page is retained and shows the error.
- **Process:** One question runs per chat; with JavaScript only the window is updated.
After a restart, open questions are “interrupted” and are not
sent again. Without the Stage `settings_help` in `prompts.yaml`, the chat gives a
setup note.

| Setting / key | Effect and values | Application |
| --- | --- | --- |
| Offer help chat (`help_chat.enabled`) | Yes (true) offers the help chat: It explains settings and operating paths with the bundled documentation via the active AI connection; for this, the question, short History and matching sections go to the AI provider and cause costs. No (false) accepts no new questions; the documentation remains readable. Default Yes. | At runtime |
| Help chat: longest question (characters) (`help_chat.max_question_chars`) | Longest question to the help chat: 100–8000 characters; default 4000. Longer questions are rejected with a notice, not shortened. | At runtime |

## Help chat <!-- mailhelp-id:web-einstellungen/hilfschat-2 -->

| Help chat: Documentation per question (bytes) (`help_chat.max_context_bytes`) | At most this many bytes of documentation are included per question: 2000–48000; default 24000. More context can make answers more complete and increases costs. | While running |
| Help chat: Questions per minute (`help_chat.requests_per_minute_per_session`) | New questions per session and minute: 1–20; default 6. The global AI call limit applies additionally; a repeated query of the same question does not count. | While running |

## Additional Notes <!-- mailhelp-id:web-einstellungen/weitere-hinweise -->

| Area | Explanation |
| --- | --- |
| Models (read-only) | The table shows the AI models actually used, parameters and their source. Other models can change quality, speed and costs. Parameters and models are maintained in prompts.yaml; starting with --ollama can replace the model selection. Here, the display is read-only. |
| Notifications | Enable Push registers this browser for content-neutral notifications; email subject and email body are not transmitted. Disable Push ends this browser's subscription. Other Devices remain unchanged. The feature requires Web Push enabled on the server side and your browser permission; HTTPS or localhost is required. |

## Appointment durations and proposal review (2.4) <!-- mailhelp-id:web-einstellungen/termindauern-und-vorschlagsabgleich-24 -->

| Setting | Effect |
| --- | --- |
| `event_defaults.video_duration_minutes` · Default duration of video conference (minutes) | Default duration of video conference: 1–1440 minutes; default 60. Adds a missing end only with an unambiguous start and documented online participation. Explicit end times and durations take precedence. Existing proposals are not automatically converted; saving does not authorize any calendar action. |
| `event_defaults.in_person_duration_minutes` · Default duration of in-person appointment (minutes) | Default duration of in-person appointment: 1–1440 minutes; default 180. Adds a missing end with documented in-person attendance and unambiguous start. An address in the signature does not document in-person attendance. Explicit time specifications take precedence; the assumption is displayed in the proposal. |
| `proposal_reconciliation.max_semantic_candidates` · Review: at most AI candidates | 1–50 possible open proposals per semantic AI comparison; default 8. Further plausible matches block automatic assignment instead of being considered a missing duplicate. A missing comparison prompt requires manual assignment in unclear cases. |

## IServ Accounts (3.3.10) <!-- mailhelp-id:web-einstellungen/iserv-konten-3310 -->

Under `/einstellungen/iserv`, IServ accounts for parent letters are created, changed, activated, deactivated, and removed. Per account: display name, HTTPS address of the school (a copied IServ link or the address without `https://` is shortened to the school address), the mailbox whose target profile and defaults apply, and optionally the start limit (`TT.MM.JJJJ [HH:MM]` or ISO 8601; empty: that of the mailbox). The page names invalid fields with their cause.
Every change is a draft; it is applied after the current diagnosis `iserv` and explicit confirmation. Parent letters are always considered relevant. The access data belongs on the Access Data page. Effect after the next restart.

## Credentials (3.3.11) <!-- mailhelp-id:web-einstellungen/zugangsdaten-3311 -->

`/einstellungen/zugangsdaten` shows for each required entry only "stored" or "missing" and
accepts new values only in write mode: `IMAP_<n>_USERNAME/_PASSWORD` per mailbox (for mailbox 1 in the
older format `IMAP_USERNAME/_PASSWORD`), `ISERV_<n>_USERNAME/_PASSWORD` per IServ account,
`OPENROUTER_API_KEY`, `TELEGRAM_BOT_TOKEN` when Telegram is active and the secrets of the Calendar and
Tasks services per target profile. Each change is explicitly confirmed; only the
affected line in `.env` is replaced. `MAILHELP_WEB_SECRET` remains excluded. Values from the process environment
take precedence and are marked as such. Diagnostics and setup read new values
immediately, email retrieval after the next restart.

## Mailboxes and Target Profiles (3.2) <!-- mailhelp-id:web-einstellungen/postfaecher-und-zielprofile-32 -->

Under `/einstellungen/postfaecher`, each Mailbox shows the tabs Targets, Filters, Topics, Replies and Notifications. Unassigned fields inherit globally; Reset removes the local rule.
Profile 1 is the existing `targets` section; additional profiles are managed at `/einstellungen/zielprofile`.
Used profiles can only be removed after resolving all displayed references.

| Local Setting | Effect |
| --- | --- |
| `target_profile` | ID 1–99 of a configured profile; applies to new Proposals after restart. Existing Proposals remain bound. |
| `personal_info`, `smart_reply` | Own role/signature and reply drafts for this Mailbox; storage remains in the origin Mailbox. |
| `notifications.quiet_hours`, `notifications.categories` | Inherited quiet hours and category channels; shared queue with separate Mailbox bundles. |
| `daily_briefing` | Include/exclude this Mailbox as its own section. |
| `activity_report_folder` | Preselected folder for activity reports. |
| `retention.full_mail_days` | Retain full texts for a shorter time than globally; `disabled` removes content, `unlimited` only with globally unlimited retention. |
| `event_defaults` | Local default durations in minutes, 1–1440; explicit Email times take precedence. |
| Topic scope | Global, only this Mailbox, or exclude here; own fingerprints only of affected Mailboxes. |
| Filter | Local address/Domain blocks and exact Exceptions from global blocks. |

Saving creates a setup draft. Applying it requires a renewed explicit local confirmation. Target/connection changes require current read diagnostics. The draft shows running Mails that are held back by a relevant change. Credentials are edited separately under **Settings → Credentials** directly in `.env`.
Guide: [Release 3.2](../archiv/Release-3.2.md).

## Mailbox Briefings (4.9) <!-- mailhelp-id:web-einstellungen/postfach-briefings-49 -->

Under `/einstellungen?bereich=briefing`; times are entered with comma or semicolon.

| Setting / Key | Effect and Values | Application |
| --- | --- | --- |
| Enable briefings as mailbox draft (`briefings.enabled`) | Activates scheduled briefings as IMAP drafts, default off. No SMTP sending. Enabling only authorizes draft storage; Calendar and Task actions still require their own version-related confirmation. | At runtime |
| Times for Mailbox Briefings (`briefings.times`) | Certain local times in format HH:MM, separated by comma, semicolon or space, for example 07:00, 13:00, 18:00. Uses the configured time zone. When enabled, at least one time must be specified. | At runtime |
| Target mailbox for Briefings (`briefings.mailbox`) | Target mailbox for the briefing drafts. default uses the first active mailbox; alternatively an active mailbox number. The briefing collects open decisions of all mailboxes. It is never sent to external recipients. | At runtime |
| Skip empty Mailbox Briefings (`briefings.skip_empty`) | Default true: Without open decisions and without relevant summaries, no empty draft is created. false instead creates a short all-quiet briefing. | At runtime |

## Complete Reference of Additional Settings (5.3) <!-- mailhelp-id:web-einstellungen/vollstaendige-referenz-weiterer-einstellungen-53 -->

These settings are not in the general settings areas. They are maintained in the
initial setup, on separate pages (Mailbox, IServ, target profiles, notifications), or only
in `config.yaml`. "Mandatory" means: The value must be in `config.yaml`; the
included `config.example.yaml` contains it. Values without a Field apply with their default.
Changes in `config.yaml` take effect after a restart unless otherwise stated.

### Initial setup and Mailbox 1 (older single format) <!-- mailhelp-id:web-einstellungen/ersteinrichtung-und-postfach-1-aelteres-einzelformat -->

| Key | Effect and values | Access path |
| --- | --- | --- |
| `imap.host` | Mail server of the first mailbox in the older single format, e.g. `imap.example.org`; 1–253 characters. Without `imap.mailboxes`, this block describes Mailbox 1. | Initial setup |
| `imap.port` | Port of the mail server, 1–65535; commonly 993 (SSL/TLS) or 143 (STARTTLS). | Initial setup |
| `imap.connection_mode` | Connection type `ssl`, `starttls` or `plain` (unencrypted, only useful in your own network); if not specified, `ssl`. | Initial setup |
| `imap.folders` | Folders that are read, 1–100 entries; the first is the inbox. | Initial setup |
| `imap.primary_folder` | Folder that counts as the inbox and must be in `imap.folders`; if not specified, the first entry of `imap.folders`. | Initial setup |
| `imap.drafts_folder` | Folder for reply and briefing drafts; if not specified, `Drafts`. | Initial setup |
| `imap.historical_start` | Start boundary: older Mails are not processed (Date with time and time zone). Empty means all existing Mails. `mailhelp --ignore-historical-start` overrides it for one retrieval. | Initial setup |
| `telegram.enabled` | Telegram bot for queries, confirmations and notifications; default on. Off: operation only via the Web interface. | Initial setup |
| `push.enabled` | Offer Web Push (content-neutral notices) server-side; default off. Each device additionally enables push itself. Only via HTTPS or localhost. | Initial setup |
| `push.subject` | Operator contact address for the push service (VAPID), format `mailto:name@domain`; default `mailto:admin@example.invalid` (example value; replace before use). | Initial setup |
| `daily_briefing.enabled` | Daily overview via Telegram; default off. | Initial setup, Notifications |
| `daily_briefing.time` | Time of the daily overview in HH:MM format in the configured time zone; default 07:30. | Initial setup, Notifications |

### Mailboxes (`imap.mailboxes`) <!-- mailhelp-id:web-einstellungen/postfaecher-imapmailboxes -->

Each mailbox is an entry in the `imap.mailboxes` list. Mailboxes are created, checked and changed under
**Settings → Mailboxes**; unset local fields inherit
the global setting. Credentials are stored as `IMAP_<n>_USERNAME`/`IMAP_<n>_PASSWORD` in `.env`.

| Key | Effect and Values | Access path |
| --- | --- | --- |
| `imap.mailboxes[].id` | Number of the mailbox, 1–99; determines the names of the credentials. Assigned when created and not changed. | Mailbox page |
| `imap.mailboxes[].label` | Display name, 1–40 characters; default “Mailbox”. | Mailbox page |
| `imap.mailboxes[].enabled` | Whether the mailbox is retrieved; default on. A disabled mailbox remains listed. | File |
| `imap.mailboxes[].host` | Mail server, 1–253 characters (required). | Mailbox page |
| `imap.mailboxes[].port` | Port 1–65535 (required). | Mailbox page |
| `imap.mailboxes[].connection_mode` | `ssl` (default), `starttls` or `plain`. | Mailbox page |
| `imap.mailboxes[].folders` | Read folders, 1–100 (required); the first is the inbox. | Mailbox page |
| `imap.mailboxes[].primary_folder` | Inbox; default `INBOX`. | Mailbox page |
| `imap.mailboxes[].drafts_folder` | Drafts folder, 1–500 characters; default `Drafts`. | Mailbox page |
| `imap.mailboxes[].historical_start` | Start boundary of this mailbox; empty means all Mails. | Mailbox page |
| `imap.mailboxes[].own_addresses` | Additional own sender addresses (aliases), at most 20; the IMAP username already counts. Mails from these addresses are considered own Note or forwarding. | File |
| `imap.mailboxes[].target_profile` | Target profile 1–99 for new Proposals of this mailbox; default 1. Existing Proposals remain bound to their target. | Mailbox page (Targets) |
| `imap.mailboxes[].mail_client` | Where “Open original email” leads: `auto` (default), `apple_mail`, `gmail_web`, `outlook_web` or `none`. | Mailbox page (Targets) |
| `imap.mailboxes[].event_defaults.video_duration_minutes` | Local default duration for video appointments, 1–1440 minutes; empty inherits global. | Mailbox page (Targets) |
| `imap.mailboxes[].event_defaults.in_person_duration_minutes` | Local default duration for in-person appointments, 1–1440 minutes; empty inherits global. | Mailbox page (Targets) |
| `imap.mailboxes[].personal_info` | Own role, signature and details for reply drafts of this mailbox, up to 2000 characters; empty inherits global. | Mailbox page (Replies) |
| `imap.mailboxes[].smart_reply` | Reply drafts for this mailbox; empty inherits global. | Mailbox page (Replies) |
| `imap.mailboxes[].auto_draft` | Place drafts in the drafts folder without a click; empty inherits global (default off). | Mailbox page (Replies) |
| `imap.mailboxes[].activity_report_folder` | Preselected folder for activity reports. | Mailbox page (Replies) |
| `imap.mailboxes[].retention.full_mail_days` | Retain full texts for a shorter time than global: days, `disabled` (remove immediately) or `unlimited` (only with globally unlimited retention). | Mailbox page (Replies) |
| `imap.mailboxes[].daily_briefing` | Show this mailbox in the daily briefing as its own section; default on. | Mailbox page (Notifications) |
| `imap.mailboxes[].notifications.quiet_hours.enabled` | Own quiet hours for this mailbox; empty inherits global. | Mailbox page (Notifications) |
| `imap.mailboxes[].notifications.quiet_hours.start` | Start of quiet hours, HH:MM; empty inherits global. | Mailbox page (Notifications) |
| `imap.mailboxes[].notifications.quiet_hours.end` | End of quiet hours, HH:MM; empty inherits global. | Mailbox page (Notifications) |
| `imap.mailboxes[].notifications.quiet_hours.allow_system_errors` | Report system errors despite quiet hours; empty inherits global. | Mailbox page (Notifications) |
| `imap.mailboxes[].notifications.categories.decisions` | Channels (`telegram`, `web_push`) for decisions of this mailbox; empty inherits global. | Mailbox page (Notifications) |
| `imap.mailboxes[].notifications.categories.action_results` | Channels for results of entries; empty inherits global. | Mailbox page (Notifications) |
| `imap.mailboxes[].notifications.categories.daily_briefing` | Channels for the daily briefing; empty inherits global. | Mailbox page (Notifications) |
| `imap.mailboxes[].notifications.categories.system_errors` | Channels for system errors; empty inherits global. | Mailbox page (Notifications) |

Changes on the mailbox page are drafts; they are applied after renewed explicit
confirmation. The application occurs between mail cycles or after a restart (see above).

### IServ Accounts (`iserv.accounts`) <!-- mailhelp-id:web-einstellungen/iserv-konten-iservaccounts -->

| Key | Effect and Values | Access path |
| --- | --- | --- |
| `iserv.accounts[].id` | Number 1–10; determines the credentials `ISERV_<n>_USERNAME`/`_PASSWORD`. | IServ page |
| `iserv.accounts[].label` | Display name, 1–40 characters; default „Elternbriefe“. | IServ page |
| `iserv.accounts[].server` | HTTPS address of the school (required, up to 253 characters); a copied IServ link is shortened to the school address. | IServ page |
| `iserv.accounts[].mailbox` | Mailbox 1–99, whose target profile and defaults apply; must be active. Default 1. | IServ page |
| `iserv.accounts[].enabled` | Retrieve account; default on. | IServ page |
| `iserv.accounts[].historical_start` | Start limit; empty adopts that of the mailbox. | IServ page |

### Additional target profiles (`target_profiles`) <!-- mailhelp-id:web-einstellungen/weitere-zielprofile-targetprofiles -->

Profile 1 is the `targets` section; additional profiles (ID 2–99) are managed in
**Settings → Target profiles**. The fields correspond to `targets` (see “Targets”).

| Key | Effect and values | Access path |
| --- | --- | --- |
| `target_profiles[].id` | Number 2–99 (required). | Target profile page |
| `target_profiles[].label` | Display name, 1–40 characters (required). | Target profile page |
| `target_profiles[].calendar_provider` | `google` (default), `caldav` or `outlook`. | Target profile page |
| `target_profiles[].task_provider` | `todoist` (default), `microsoft_todo`, `caldav`, `apple_reminders`, `google_tasks` or `notion` (7.2). | Target profile page |
| `target_profiles[].google_calendar` | Calendar ID at Google, up to 500 characters. | Target profile page |
| `target_profiles[].todoist_project` | Todoist project ID, up to 500 characters. | Target profile page |
| `target_profiles[].caldav_calendar_url` | Address of the CalDAV calendar collection, up to 2000 characters. | Target profile page |
| `target_profiles[].caldav_task_url` | Address of the CalDAV task collection (also Apple Reminders), up to 2000 characters. | Target profile page |
| `target_profiles[].outlook_calendar` | Outlook calendar, default `default`. | Target profile page |
| `target_profiles[].microsoft_todo_list` | Microsoft To Do list, default `default` (list “Tasks”). | Target profile page |
| `target_profiles[].google_tasks_list` | Google Tasks list, default `@default` (first list of the account). | Target profile page |
| `target_profiles[].microsoft_tenant` | Microsoft tenant for sign-in, default `common`. | Target profile page |
| `target_profiles[].removal_window_minutes` | Time window in minutes after creating an entry during which it can be removed again: 1–1440; default 10. | Target profile page |

### Notion as Task Target (7.2) <!-- mailhelp-id:web-einstellungen/notion-als-aufgabenziel-72 -->

Only in `config.yaml` (section `targets`) and per target profile (`target_profiles[]`, same names).
Mailhelp addresses each property via its ID so that a renamed field still matches. If a property is missing or its type changes, Mailhelp blocks new attachments until the new mapping.

| Key | Effect and Values | Access path |
| --- | --- | --- |
| `targets.notion_data_source_id` | ID of the Notion data source (32 hex characters, with or without hyphens), not that of the database. Required for `task_provider: notion`. | File |
| `targets.notion_properties.title` | ID of the title property (type title). Required for Notion. | File |
| `targets.notion_properties.description` | ID of the text property for the description (type text). Required for Notion. | File |
| `targets.notion_properties.due` | ID of the date property for the deadline (type date); remains empty without a deadline. Required for Notion. | File |
| `targets.notion_properties.source` | ID of the URL property for the link to the email; empty if there is no https link. Required for Notion. | File |
| `targets.notion_properties.operation_key` | ID of the text property for the operation key, via which Mailhelp locates an unclear attachment again. Required for Notion. | File |
| `targets.notion_properties.status` | Optional: ID of a status, select, or checkbox property. Without it, Mailhelp does not recognize completed Notion tasks. | File |
| `targets.notion_open_status` | Option ID that new pages receive in the status field; required with a status or select field. | File |
| `targets.notion_done_statuses` | Option IDs that count as done; at most 50. | File |
| `target_profiles[].notion_data_source_id` | As `targets.notion_data_source_id`, for this target profile. | Target profile page |
| `target_profiles[].notion_properties.title` | As `targets.notion_properties.title`. | Target profile page |
| `target_profiles[].notion_properties.description` | As `targets.notion_properties.description`. | Target profile page |
| `target_profiles[].notion_properties.due` | As `targets.notion_properties.due`. | Target profile page |
| `target_profiles[].notion_properties.source` | As `targets.notion_properties.source`. | Target profile page |
| `target_profiles[].notion_properties.operation_key` | As `targets.notion_properties.operation_key`. | Target profile page |
| `target_profiles[].notion_properties.status` | As `targets.notion_properties.status`. | Target profile page |
| `target_profiles[].notion_open_status` | As `targets.notion_open_status`. | Target profile page |
| `target_profiles[].notion_done_statuses` | As `targets.notion_done_statuses`. | Target profile page |

### Notifications (`notifications`) <!-- mailhelp-id:web-einstellungen/benachrichtigungen-notifications -->

Under **Settings → Notifications** and in the initial setup. If the entire `notifications` block is missing, Mailhelp reports all categories via Telegram (decisions and daily briefing additionally via push, if active) with content `summary`. If the block is present, its values apply.

| Key | Effect and values | Access path |
| --- | --- | --- |
| `notifications.quiet_hours.enabled` | Quiet hours: during this time range, notifications are held back; default off. | Notifications |
| `notifications.quiet_hours.start` | Start, HH:MM; default 22:00. | Notifications |
| `notifications.quiet_hours.end` | End, HH:MM; default 07:30. | Notifications |
| `notifications.quiet_hours.allow_system_errors` | Report system errors also during quiet hours; default off. | Notifications |
| `notifications.batching.enabled` | Bundle notifications within a time window; default off. | Notifications |
| `notifications.batching.window_seconds` | Batching window 1–86400 seconds; default 300. | Notifications |
| `notifications.categories.decisions` | Channels (`telegram`, `web_push`) for decisions; an empty list does not notify this category. | Notifications |
| `notifications.categories.action_results` | Channels for results of entries. | Notifications |
| `notifications.categories.daily_briefing` | Channels for the daily briefing. | Notifications |
| `notifications.categories.system_errors` | Channels for system errors. | Notifications |
| `notifications.telegram_content` | `neutral` (default): Telegram notifications without email contents; `summary`: with a short overview of the decisions or the daily briefing. | Notifications |
| `notifications.delivery.max_attempts` | Delivery attempts per notification, 1–10; default 3. | Notifications |
| `notifications.delivery.initial_backoff_seconds` | Wait time before the second attempt, 1–86400 seconds; default 30. | Notifications |
| `notifications.delivery.max_backoff_seconds` | Longest wait time between attempts, 1–86400 seconds; default 900. | Notifications |
| `notifications.delivery.max_pending` | Maximum queued notifications, 1–100000; default 1000. | Notifications |
| `notifications.delivery.history_days` | Retention of delivery history, 1–3650 days; default 30. | Notifications |

### AI integration, reanalysis and verification <!-- mailhelp-id:web-einstellungen/ki-anbindung-nachanalyse-und-nachpruefung -->

| Key | Effect and values | Access path |
| --- | --- | --- |
| `llm.provider` | `openrouter` (default) or `ollama` (local server). `--ollama HOST:PORT` at start overrides the choice. With `openrouter`, `OPENROUTER_API_KEY` in `.env` is required. | File |
| `llm.ollama_address` | Address of the Ollama server with `llm.provider: ollama`; default `localhost:11434`, also `http://localhost:11434`. | File |
| `retries.provider_retry` | Retries of an AI call after a temporary provider error, 0–10 (required). Each retry counts against `limits.llm_calls_per_minute`. | File |
| `retries.json_repair` | Repair attempts when the AI does not deliver valid JSON, 0–10 (required). | File |
| `retries.schema_repair` | Repair attempts when the JSON does not match the expected structure, 0–10 (required). | File |
| `reanalysis.enabled` | Offer “Task or Event missed?”; default on. | File |
| `reanalysis.max_llm_calls_per_job` | AI calls per reanalysis, 1–10; default 5 (three stages and two retries). | File |
| `reanalysis.max_attempts` | Attempts per model call after error or restart, 1–5; default 2. | File |
| `reanalysis.max_jobs_per_day` | Started reanalyses per day across all Mails, 1–500; default 20 (cost protection). | File |
| `write_verification.max_attempts` | Verification retrievals after an entry, 1–10; default 5. The first retrieval is attempt 1. | File |
| `write_verification.retry_delays_seconds` | Wait time before each further retrieval, exactly `max_attempts − 1` values of 1–3600 seconds; default `[1, 5, 15, 60]`. A provider `Retry-After` can be longer. | File |
| `write_verification.max_elapsed_seconds` | Maximum duration of the check, 10–86400 seconds, at least the sum of the wait times; default 300. After that, the entry explicitly remains unverified. | File |

### Security limits when parsing emails <!-- mailhelp-id:web-einstellungen/sicherheitsgrenzen-beim-zerlegen-von-mails -->

An email that exceeds one of these limits is not evaluated: it appears with the message “The message exceeds a security limit” and without an AI call. The defaults are sufficient for ordinary emails; increase them only for repeatedly affected, trustworthy emails.

| Key | Effect and values | Configuration method |
| --- | --- | --- |
| `limits.max_header_bytes` | Size of all headers, 256–1000000 bytes; default 64000. | File |
| `limits.max_display_header_characters` | Longest displayed header (sender, subject), 1–10000 characters; default 500. Longer ones are displayed as “—”. | File |
| `limits.max_mime_parts` | Parts of an email, 1–10000; default 100. | File |
| `limits.max_decoded_text_bytes` | Decoded text of all parts, 1–100000000 bytes; default 1000000. | File |
| `limits.max_html_characters` | Length of the HTML part, 1–100000000 characters; default 1000000. | File |
| `limits.max_html_tags` | HTML elements, 1–1000000; default 20000. | File |
| `limits.max_html_depth` | Nesting depth of the HTML, 1–10000; default 100. | File |

### Paths, Logs and Web Server <!-- mailhelp-id:web-einstellungen/pfade-protokolle-und-webserver -->

| Key | Effect and values | Access path |
| --- | --- | --- |
| `data_directory` | Directory of state data (required); under it `production` or `test` depending on test mode. Relative to the configuration. | File |
| `logging.directory` | Directory of the logs (required); `--log-directory` overrides it for one start. | File |
| `logging.console.format` | Screen output as `text` (default) or `jsonl`. | File |
| `logging.file.filename` | File of the application log in the log directory (required). | File |
| `logging.file.format` | `jsonl` (default) or `text`. | File |
| `logging.file.max_bytes` | Size at which the file is rotated, greater than 0 (required). | File |
| `logging.file.backup_count` | Retained older files, from 0 (required). | File |
| `logging.file.retention_days` | Maximum age of the log files, 1–3650 days (required). | File |
| `logging.llm.filename` | File of the AI log (required). Contents of requests and responses are only there with `logging.llm.include_requests`/`include_responses`. | File |
| `logging.llm.format` | `jsonl` (default) or `text`. | File |
| `logging.llm.max_bytes` | Rotation size, greater than 0 (required). | File |
| `logging.llm.backup_count` | Retained older files, from 0 (required). | File |
| `logging.llm.retention_days` | Maximum age, 1–3650 days (required). | File |
| `logging.telegram.filename` | File of the Telegram message log; default `telegram/messages.jsonl`. | File |
| `logging.telegram.format` | `jsonl` (default) or `text`. | File |
| `logging.telegram.max_bytes` | Rotation size, greater than 0; default 10000000. | File |
| `logging.telegram.backup_count` | Retained older files, from 0; default 5. | File |
| `logging.telegram.retention_days` | Maximum age, 1–3650 days; default 30. | File |
| `logging.modules` | Log level per module, e.g. `openrouter: INFO`; default empty. | File |
| `timeouts.telegram_poll_seconds` | Wait time of a Telegram query for new messages, 1–50 seconds (required). | File |
| `web.enabled` | Start web interface; default off. | File |
| `web.host` | Network address of the web server; default `127.0.0.1` (only this PC). `0.0.0.0` is necessary for `web.lan_access`. | File |
| `web.port` | Port 1–65535; default 8765. | File |
| `web.allowed_hosts` | Allowed host specifications in the browser call (protection against DNS rebinding), 1–20 entries; default `127.0.0.1:8765`, `localhost:8765`. | File |
| `web.google_redirect_uri` | Redirect URI of the Google sign-in; must be entered in the Google Cloud Console. Default `http://localhost:8765/auth/google/callback`. | File |
| `web.notion_redirect_uri` | Redirect URI of the Notion sign-in (7.2.5); must be entered exactly like this in the public Notion connection. HTTPS or localhost, path `/auth/notion/callback`. Default `http://localhost:8765/auth/notion/callback`. | File |
