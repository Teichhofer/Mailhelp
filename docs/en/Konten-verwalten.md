# Manage accounts <!-- mailhelp-id:konten-verwalten/konten-verwalten -->

From 8.1, the add-mailbox form offers the same local provider defaults as initial
setup. Custom domains can be assigned to a hosting provider explicitly; manual
setup remains available. Gmail/Microsoft mailbox OAuth needs operator registration
and a separate grant. New readers replace the affected mailbox between mail cycles;
a failed connection keeps the previous reader and leaves other mailboxes unchanged.

Verified for Mailhelp 8.1. Add, change and remove additional mailboxes, IServ accounts and additional Calendar/Task targets in an already set up installation.

**Principle:** Credentials are stored only in `.env` and are maintained under **Settings → Credentials**; only “stored” or “missing” is displayed. Changes to mailboxes and targets are drafts and are only applied after a renewed explicit confirmation. None of these pages creates Tasks or Events.

## Add another mailbox <!-- mailhelp-id:konten-verwalten/ein-weiteres-postfach-hinzufuegen -->

**Prerequisite:** Server, port, connection type and credentials of the mailbox.

1. Open **Settings → Mailboxes** and select **Add mailbox**.
2. Fill in:
   - **Display name**, e.g. “School”.
   - **IMAP server** and **Port**.
   - **Connection type**: **SSL/TLS (usually port 993)**, **STARTTLS (usually port 143)** or
     **Unencrypted (only in your own network)**.
   - **Username (usually the full email address)** and **Password or app password**.
   - **Folders (comma-separated, the first is the inbox)** and **Folder for
     reply drafts**.
   - **Do not process older mails before (empty: all existing mails)**, pre-filled with today.
3. Select **Check connection and activate mailbox**.

**Result:** After successful verification of login, folder list and read access, `config.yaml` and `.env` are saved (`IMAP_<n>_USERNAME`/`IMAP_<n>_PASSWORD`). The new mailbox is added between two mail cycles, without restart. If the check fails, all entries except the password are retained; the message names the cause without server response. Duplicate accounts are rejected. If you do not want to activate immediately, select **Instead, add as draft only**.

## Assign a mailbox to another calendar or another task list <!-- mailhelp-id:konten-verwalten/ein-postfach-einem-anderen-kalender-oder-einer-anderen-aufgabenliste-zuordnen -->

1. Under **Settings → Target profiles**, use **Add target profile** to create a profile
   (name, calendar service, task service and the respective identifiers) – see
   “Other targets” below.
2. **Settings → Mailboxes**, open the mailbox, tab **Targets**, set **Target profile** to the
   new profile.
3. **Review draft** and then confirm **Take draft**.

**Result:** New proposals of this mailbox go to the new target. Already existing
proposals remain bound to their previous target; for the new target a new confirmation is
required.

## Rules per Mailbox <!-- mailhelp-id:konten-verwalten/regeln-je-postfach -->

On the mailbox page there are the tabs **Goals**, **Filters**, **Topics**, **Replies** and
**Notifications**. Unset fields inherit the global setting; Reset
removes the local rule. Examples: custom default durations for events, custom signature for
reply drafts, shorter retention, custom quiet hours, local sender blocks or
exceptions from global blocks. All fields: [Settings](Web-Einstellungen.md#postfächer-imapmailboxes).

## Add IServ account <!-- mailhelp-id:konten-verwalten/iserv-konto-ergaenzen -->

1. Open **Settings → IServ accounts**.
2. Under **Activate directly**, enter display name, Address of the school (a copied IServ link is shortened to the school address), the Mailbox whose target profile and standards apply, optionally a start limit, as well as username and password. Empty access fields use already stored values (`ISERV_<n>_USERNAME`/`ISERV_<n>_PASSWORD`).
3. Select **Check connection and activate account**.

**Result:** Only after successful login are the account and access data saved. Retrieval starts without a restart in the next secure mail cycle; if applicable, answer open queries first. Parent letters always count as relevant. Anyone who does not want to activate immediately selects **Add IServ account as draft**.

## Additional targets (Calendars and task lists) <!-- mailhelp-id:konten-verwalten/weitere-ziele-kalender-und-aufgabenlisten -->

Profile 1 is the target from the initial setup (**Edit default profile 1**). Additional profiles
(number 2–99) under **Settings → Target profiles**:

1. **Add target profile**, choose designation, calendar service (Google, CalDAV, Outlook) and
   task service (Todoist, Microsoft To Do, CalDAV, Apple Reminders).
2. Enter the identifiers; for Google or Microsoft, sign in via **Connect Google** or
   **Connect Microsoft** and for Google **Select Google Calendar** or
   **Select Google Tasks list**. The target selection is saved as a setup draft.
3. **Check accesses**: The diagnostic only reads and creates nothing. In a customer instance choose
   **Check own connections** on the target profiles page instead (since 8.8.4).
4. Check the draft and take it.

## Change, deactivate, and remove <!-- mailhelp-id:konten-verwalten/aendern-deaktivieren-und-entfernen -->

| Task | Path | Effect |
| --- | --- | --- |
| Change mailbox setting | Mailbox page, select tab, **Review draft**, **Take draft** | between mail cycles or after restart |
| Remove mailbox | Mailbox page, **Remove mailbox**, confirm | is removed from the configuration; no longer retrieved after restart |
| Temporarily switch off mailbox | in `config.yaml` `enabled: false` for the mailbox | after restart |
| Remove target profile | Target profile page, **Remove profile** | only possible when no mailbox uses it anymore (“Used by: …”) |
| Change, deactivate, or remove IServ account | IServ page; the change is saved as a draft | after explicit taking of the draft and restart |
| Renew credentials | **Settings → Credentials** | Diagnostics immediately, email retrieval after restart |

## If something does not work <!-- mailhelp-id:konten-verwalten/wenn-etwas-nicht-klappt -->

For a rejected mailbox OAuth sign-in, “Reconnect mailbox” in the warning opens the
affected Google or Microsoft mailbox. Restart the flow after a configuration or
credential change. For iCloud, start with the suggested name before `@`; if sign-in
fails, try the full iCloud address as described in Apple's instructions.

**Check own connections** (since 8.8.4, on **Mailboxes** and **Target profiles**) checks all own
mailboxes, calendars and task lists read-only. Each connection then shows "reachable", "Renew sign-in",
"temporarily unreachable", "Check the setting" or "not set up". Nothing is created or sent. A new check is
possible a few seconds after the last one.

| Situation | Next Stage |
| --- | --- |
| “There are already … Mailboxes set up.” | Remove or change an existing Mailbox |
| Check reports incorrect login credentials | Username is usually the full Address; with two-factor protection use an app password |
| Folder missing | Enter the folder name exactly as the server reports it; the check shows the found list |
| Target unreachable | **Check access** (in a customer instance **Check own connections**); for Google or Microsoft, renew the sign-in |
| Target profile cannot be removed | First assign Mailboxes listed under “Used by” to another profile |
