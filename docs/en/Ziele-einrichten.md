# Connect Calendar and Tasks <!-- mailhelp-id:ziele-einrichten/kalender-und-aufgaben-verbinden -->

Verified for Mailhelp 7.2; provider documentation compared on 11 and 16 November 2026. A **target profile** determines into which calendar and which task list
confirmed proposals of a mailbox are entered. Profile 1 is the `targets` section
from initial setup; additional profiles are managed in **Settings → Target profiles**. An
**account** is the access at the provider (credentials in `.env`), the calendar or
list ID the specific target within this account.

Mailhelp writes only after your explicit confirmation of exactly the displayed
proposal version and then checks each entry with a fresh retrieval.
Created entries can be removed again within the deadline (by default 10 minutes, `targets.removal_window_minutes`)
via web or Telegram, provided the target allows safe removal:
Google Calendar, Outlook, Todoist and CalDAV calendars. For Microsoft To Do, CalDAV tasks,
Apple Reminders and Google Tasks, Mailhelp does not offer removal; even a direct command is
rejected. Please edit such entries at the provider.

## Providers and their capabilities <!-- mailhelp-id:ziele-einrichten/anbieter-und-ihre-faehigkeiten -->

| Provider | Role | Access (`.env`) | Identifier | What is checked | Limits |
| --- | --- | --- | --- | --- | --- |
| Google Calendar | Calendar | `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, `GOOGLE_OAUTH_REFRESH_TOKEN` | Calendar ID or `primary` | Title, times, all-day, location, description | Redirect URI must be entered in the Google Console |
| Todoist | Tasks | `TODOIST_TOKEN` | Project ID | Title, description, due date, project | Changes and cancellations only for events |
| Outlook | Calendar | `MICROSOFT_CLIENT_ID`, optional `MICROSOFT_CLIENT_SECRET`, sign-in via device code | Calendar or `default` | like Google | Cancellations delete the event |
| Microsoft To Do | Tasks | like Outlook | List or `default` ("Tasks") | Title, description, due date day | only day-accurate, no time |
| Notion (7.2) | Tasks | `NOTION_TOKEN` (internal connection) | Data source ID and property IDs | Title, description, deadline | without a status field, no detection of done pages; no removal |
| Google Tasks (7.2) | Tasks | like Google Calendar; sign-in with Google Tasks permission | List ID or `@default` (first list) | Title, notes, due date day | only day-accurate; an exact deadline is in the text; no removal |
| CalDAV | Calendar and Tasks | `CALDAV_USERNAME`, `CALDAV_PASSWORD` (app password) | Address of the collection | Resource with UID, fields, status | Recurring events are never changed |
| Apple Reminders | Tasks (via CalDAV) | like CalDAV (iCloud app password) | Address of the list | like CalDAV | lists switched to new iCloud reminders are not reachable via CalDAV |
| Calendar file | Calendar (via Telegram) | – | – | not checkable | whether the file was imported, Mailhelp cannot know |

## Google Calendar <!-- mailhelp-id:ziele-einrichten/google-kalender -->

1. Under **Settings → Credentials**, store the Client ID and Client Secret of the
   web application client; the **Google redirect URI (web application client)**
   must be entered in the Google Cloud Console.
2. Select **Connect Google**, consent in the Google window, and **Complete Google sign-in**.
3. **Select Google Calendar** and take the desired calendar.
4. **Check accesses**.

Alternatively without a web application client: [Google: OAuth Playground guide](../Google-OAuth-Playground.md).

For an external Google project with publishing status “Testing”, the refresh token
can expire after seven days. Then renew the sign-in and check the project status.

## Google Tasks <!-- mailhelp-id:ziele-einrichten/google-tasks -->

1. In the Google project, enable the **Google Tasks API**. If it is off, **Check access**
   reports exactly that.
2. Select `google_tasks` as the task service and enter the **Google Tasks list** (`@default`
   for the first list of the account or the ID of a list).
3. Run **Connect Google** again: the sign-in now additionally requests the permission for
   Google Tasks (`https://www.googleapis.com/auth/tasks`). Already granted Calendar permissions remain.
   On a computer, this also works with `mailhelp --google-auth --config-directory .`; the
   sign-in requests exactly the permissions that the profile uses.
4. Open **Select Google Tasks list** in the setup or in the target profile, select the desired
   existing list and **Save as draft**. Mailhelp reads all available pages.
   On a read error, the selection is aborted.
5. Review the setup draft, **Check access**, and take the Settings.

The list selection creates a versioned draft. The first Task then requires the explicit confirmation of its suggestion version. Preview and Telegram show “Google Tasks adopts the Date; the exact Deadline is in the text.”.

Google Tasks stores only a day for a Task, no time. Mailhelp enters the confirmed day in the configured time zone and additionally writes an exact Deadline into the text, for example `Frist: 12.05.2026, 18:00 Uhr (Europe/Berlin)`. There is no time-exact reminder from Google for this. Without a Deadline, the Date remains empty.

## Notion <!-- mailhelp-id:ziele-einrichten/notion -->

Mailhelp creates a page in a Notion data source for each confirmed task. You set up the table yourself; Mailhelp does not create data sources or properties.

1. In Notion, create a database with these properties: Title, Description (Text), Deadline (Date), Source (URL), Process (Text), and optionally Status (Status, Select, or Checkbox).
2. In Notion, create an internal connection with the capabilities Read content and Insert content, and share the database with this connection.
3. Store the token as `NOTION_TOKEN` (additional profiles: `NOTION_2_TOKEN`, etc.). Alternatively, a public connection: store `NOTION_CLIENT_ID` and `NOTION_CLIENT_SECRET`, enter the redirect URI `web.notion_redirect_uri` in Notion, and under **Settings → Target profiles** select **Connect Notion**. Mailhelp stores the rotating tokens in `notion-token.json` next to `.env` and remains bound to the selected workspace.
4. Under **Settings → Target profiles**, select **Select Notion data source**; the data sources shared for the connection are displayed. Then **Map Notion properties**: for each field, a property of the matching type and optionally the status field with the option for new pages and the options that count as done. Both are saved as a draft and applied like any settings change. Then set the task service to Notion. Alternatively, the IDs can be entered directly in `config.yaml` (see `config.example.yaml`).
5. **Check access**: Mailhelp reads the schema and reports a missing property or an incorrect type. Mailhelp does not create a test page.

If a property is later missing or its type changes, Mailhelp blocks new creations until the mapping is correct again; it is also checked directly before each creation. Without a status field, Mailhelp cannot recognize done Notion tasks.

## Todoist <!-- mailhelp-id:ziele-einrichten/todoist -->

1. Store the API token from the Todoist settings under **Settings → Credentials** as
   `TODOIST_TOKEN`.
2. Enter the **Todoist project ID** (from the project address in the browser).
3. **Check access**.

## Outlook and Microsoft To Do <!-- mailhelp-id:ziele-einrichten/outlook-und-microsoft-to-do -->

1. Store `MICROSOFT_CLIENT_ID` (app registration with “Allow public client flows”).
2. **Connect Microsoft**, **Start sign-in**, take the displayed code with **Copy code** and enter it at Microsoft. On the computer, this also works with
   `mailhelp --microsoft-login --config-directory .`.
3. Enter the **Outlook Calendar ID** or the **Microsoft To Do list** (`default` for the
   default calendar or the “Tasks” list) and **Check access**.

## CalDAV and Apple Reminders <!-- mailhelp-id:ziele-einrichten/caldav-und-apple-erinnerungen -->

1. Store `CALDAV_USERNAME` and `CALDAV_PASSWORD`; for iCloud, use an app password.
2. Enter the **CalDAV calendar address** or **CalDAV task address** as the full address of the
   collection.
3. **Check access**: Mailhelp checks in read-only mode whether the address is a calendar collection and accepts the
   matching entry type.

## Switch target safely <!-- mailhelp-id:ziele-einrichten/ziel-sicher-wechseln -->

A changed target applies to new Proposals. Proposals already displayed remain bound to the target for which they were created; after a target switch, Mailhelp locks their creation and requires a new confirmation. A target profile can only be removed when no Mailbox uses it anymore. Instructions for assignment: [Manage accounts](Konten-verwalten.md).

## Verified provider sources <!-- mailhelp-id:ziele-einrichten/gepruefte-anbieterquellen -->

Review date: November 11, 2026. This is a review of the setup instructions against official
documents; no real accounts were connected and no external entries were created.

- Google: [Calendar permissions](https://developers.google.com/workspace/calendar/api/auth)
  and [OAuth including refresh token expiration](https://developers.google.com/identity/protocols/oauth2).
- Google Tasks (November 16, 2026): [Task resource with date limit and field lengths](https://developers.google.com/workspace/tasks/reference/rest/v1/tasks)
  as well as [List with pages and done tasks](https://developers.google.com/workspace/tasks/reference/rest/v1/tasks/list)
  and [read existing task lists](https://developers.google.com/workspace/tasks/reference/rest/v1/tasklists/list).
- Notion (November 16, 2026): [API version 2026-03-11](https://developers.notion.com/reference/versioning),
  [Create page in a data source](https://developers.notion.com/reference/post-page),
  [Query data source](https://developers.notion.com/reference/query-a-data-source) and
  [Error codes](https://developers.notion.com/reference/status-codes).
- Todoist: [personal API token and API](https://developer.todoist.com/).
- Microsoft: [Device code sign-in](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-device-code)
  and [Graph permissions](https://learn.microsoft.com/en-us/graph/permissions-reference).
- CalDAV using Nextcloud as an example: [Collection address and app password with two-factor protection](https://docs.nextcloud.com/server/latest/user_manual/en/groupware/sync_windows10.html).
- Apple: [App passwords](https://support.apple.com/en-gb/102654) and
  [Change of iCloud Reminders](https://support.apple.com/en-us/102457).
  Mailhelp uses the existing CalDAV/VTODO adapter; this does not imply support
  for the new iCloud Reminders lists. This limitation remains explicitly in place.
