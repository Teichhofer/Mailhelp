# Everyday operation <!-- mailhelp-id:bedienung/alltagsbedienung -->

Tested for Mailhelp 7.0. What to do in everyday operation: review and decide on Proposals, read Mails,
answer follow-up questions, and track the State of entries.

## Open decisions <!-- mailhelp-id:bedienung/offene-entscheidungen -->

**Open** shows all proposals that need a decision. Each card names kind (task
or event), title, times, target and the evidence from the email. On large screens the
list is on the left and the selected proposal on the right; the `A` key creates the selected proposal.
The **Source evidence** (the email with attachments) is expanded immediately from 1024 px width, on
narrower screens initially collapsed; its heading names the sender and number of images.

Above the list are the quick filters and below them search, sort order and grouping.
The search finds proposal titles, subject and sender. The number in the heading then reads
something like “4 of 12”. The sort order offers “Newest email first” (default, by receipt at
Mailhelp), “Oldest email first” and “Next event / next deadline first”; entries without a date
are at the end. “Group by what is needed” divides into “Question needed”, “Ready to
confirm” and “Further check needed”. All settings are in the address and remain on
reload; “Reset” shows everything again. The bar only changes the display.

| Button | Effect |
| --- | --- |
| **Add as task** / **Add to calendar** | creates exactly this version immediately (no undo) |
| **Dismiss** | no creation |
| **Already done** | mark as done, no creation |
| **Send answer** | answers a question or changes fields (“Title: …”, “Location: …”) |
| **End editing** | discards a started change |
| **Repeat duplicate check** | after a failed check for existing entries |
| **Create again** | only after a question, if the same entry was already created earlier |

The bottom navigation remains on the phone even when scrolling at the visible
screen edge. The safe distance to the Home indicator remains clear. Via “More”
among other things Status and Settings can be reached.

### Swiping on the phone <!-- mailhelp-id:bedienung/wischen-auf-dem-telefon -->

On release, the final finger position counts. Pulled to the right or left beyond the threshold, it triggers the displayed action; normal scrolling and a swipe canceled by the browser send nothing.

On a smartphone and tablet, you swipe right to create an Event or a Task, and left to Dismiss a suggestion. The card follows your finger even diagonally. **To the right** creates (or “Relevant”), **to the left** dismisses (or “Irrelevant”). Below the card are the icon and wording of the action. From about 40 % of the card width, it is triggered on release. A short, fast swipe is also enough if it covers at least half the distance and continues in the same direction. Steeper pulling continues scrolling the list; a swipe from the screen edge remains reserved for the system gesture.

Without triggering, the card springs back. When triggered, it flies to a narrow Result strip. This shows “Processing …” and is replaced by the server result. If the server rejects, the card returns with the error message. If the response is interrupted, the status check remains active; Mailhelp sends nothing again.

If a suggestion first needs clarification, a lock appears on the right. There the card moves like a rubber band; on release, a hint states the reason. Dismissing remains possible. Unsent text blocks both directions until you send the reply or empty the field. Input fields and horizontally scrolling areas keep their controls. A normal tap on the title, link, or button still works. Mouse and wide screens from 1024 px do not use the gesture.

On first visit, a fully visible, decidable card moves gently once after a short pause. This does not trigger an action. The line below explains the directions. “×” (Close hint) or the first successful swipe ends both on this device; a hint already closed earlier remains closed. With “Reduce motion” in the system, there is no demonstration, tilt, or flight animation. The card still follows the finger directly. Without JavaScript, the forms and buttons remain the complete operating path.

On the phone, you read the title and sender/Time before the actions. The numbers for “Open decisions” and “Open” update after the decision, even with set filters. After the last decision, “All done” appears. Filter chips fading to the right can be pushed further sideways; the active filter is kept visible when opening. Explanations about relevance can be found under “What do these decisions mean?”.

## Follow-up questions and contradictions <!-- mailhelp-id:bedienung/rueckfragen-und-widersprueche -->

For changes or cancellations of an existing event, the button is called **Update existing
event** or **Cancel event**. If a change matches multiple events, you use “This event means: …” to select the right one.

If another email brings different fields for the same event or the same task, the follow-up question names both values and their origin, for example “Contradiction for the end time:
previously 16:30, according to email “Parents' evening” from 08.11. 19:30. Which end time should apply?”.
Both values are shown side by side on the card. A button such as “Keep 18:30”
or “Take 20:30” sets the value with one click and creates a new version; it is only created once you confirm this
version. For a completely different value, you change the suggestion or reply freely.
In Telegram, the same values appear in the message and as buttons below.

### Video link for an existing event <!-- mailhelp-id:bedienung/videolink-fuer-einen-bestehenden-termin -->

If an online event is already in the calendar without a dial-in link and a later email provides the link, Mailhelp does not create a second event. The card shows “Update existing event: add video link” with the link; only **Update existing event** writes it into the description of the existing event. Title, times, attendees and your notes stay unchanged.
If the event already has a different conference link, Mailhelp asks which one applies; the old link is only replaced after your choice and confirmation. If the same link is already there, the proposal stays “Already exists”. Only addresses of known providers such as Zoom, Microsoft Teams, Google Meet or Webex count as conference links, not registration or organiser pages.

A proposal that an older version already closed as existing although it contains a link offers **Compare with calendar again**. This compares the link with the current calendar and creates at most a new version, which you confirm separately.

## Proposal review <!-- mailhelp-id:bedienung/vorschlagsabgleich -->

If Mailhelp holds two Proposals for the same thing or an Email brings additional Fields for an existing Proposal, you decide in the **Proposal review** (`/abgleich`):

- **Add to this entry:** Adds the Fields from one Proposal to the existing entry. No second entry is created; you then confirm the supplemented Proposal under Open.
- **Keep as a separate proposal:** Both remain separate Proposals under Open.
- **Adopt permanent acceptance:** Remembers a fixed assignment rule for future Proposals.

If Mailhelp has submitted the assignment itself for review, the recommended button is highlighted.

## After creation <!-- mailhelp-id:bedienung/nach-dem-anlegen -->

Mailhelp retrieves every written entry fresh from the provider:

| Display | Meaning |
| --- | --- |
| Saved – entry being verified | written, verification retrieval running |
| Created and verified | the provider shows the entry with the confirmed fields |
| Entry not yet confirmed | not findable or retrieval not possible; the reason is stated |
| Entry present, fields differ | Table “Confirmed / At the provider” |
| Calendar file provided – transfer to the calendar not verifiable | file sent via Telegram |

**Check again** reads only once more; Mailhelp never changes, repairs, or repeats a
creation.

### Remove created entries again <!-- mailhelp-id:bedienung/angelegte-eintraege-wieder-entfernen -->

If you accidentally confirmed a suggestion or the occasion no longer applies, you can delete the entry from the calendar or task list again within a deadline (by default 10 minutes after creation, configurable via `targets.removal_window_minutes`):

- **Web interface:** On the result card (“Your action”) and on the suggestion detail page, the **Remove entry again** button appears during the deadline. It leads to a confirmation page that shows title, time and target. With **Really remove entry**, the entry is deleted at the provider; **Cancel** returns without changes. After the deadline expires, the direct link to the provider (“Open in calendar” or “Open task”) appears instead.
- **Telegram:** Under the message “✅ Created …”, the **Remove again** button appears. A click asks for confirmation (“Really remove: …?” with “Yes, remove” and **Cancel**).
- **Security:** If the entry at the provider has meanwhile been changed manually (e.g. by a family member), Mailhelp refuses deletion in order to protect third-party changes.
- **History:** A removed suggestion is marked in the History and under “Recently done” as **Removed again** and does not count as accepted in the acceptance rate.

## Read Mails and History <!-- mailhelp-id:bedienung/mails-nachlesen-und-verlauf -->

**Mails** lists all processed Mails. The email page shows “This is how this email was processed” with each stage and its result. If Mailhelp overlooked something, **Task or Event overlooked?** starts a targeted re-analysis (**Analyze again**, limited by a daily limit). You take new findings with **Take result** as unconfirmed proposals; **Cancel re-analysis** ends a running one.

In **History** you find every change and decision with its version. You can filter by terms, Status and Kind, under **More filters** also by Event and Time range.

## Learning mode (learning function) <!-- mailhelp-id:bedienung/lernmodus-lernfunktion -->

The learning mode helps set up topics and filters: Mailhelp reads a selection of existing
Mails, classifies them freely and suggests topics, exclusion topics, senders to ignore
and additional retrieval folders from them. It only reads: The mailbox is not changed, and no
Events or Tasks are created. Only what you explicitly confirm is applied.

All learning functions are under **Learning** (`/lernen`). The learning overview shows three cards with
purpose, current state and metrics: **Learn from Mailbox** (the learning run below),
**Learn from decisions** (improve rules from your previous decisions, see
[Learn from decisions](#aus-entscheidungen-lernen)) and **Proposals** (measure acceptance rate by Kind, topic and sender, see [Measure and improve acceptance rate](#annahmequote-messen-und-verbessern)). Opening the overview or a
card starts nothing and costs nothing. The topics themselves are managed under Settings → Topics.

### Start learning run in the web interface <!-- mailhelp-id:bedienung/lernlauf-in-der-weboberflaeche-starten -->

1. In the navigation under **Administration**, open the **Learning** page (`/lernen`) and
   select “Open learning from mailbox” (`/lernen/postfach`). The overview does not start anything.
2. Under **New learning run**, in the “1. Mailbox and folders” stage, select the **Mailbox** and
   select **Load folders**. Check the saved folders of this mailbox; additional
   folders are possible under **Additional folders (one name per line)**. Loading does not start
   a mail retrieval and works without JavaScript. In the “2. Scope” stage, specify the
   **Number of mails** (1–1000, preset 20).
3. In the “3. Costs and budget” stage, specify **Price cap USD per million tokens** and **Budget USD**. The price cap is
   your assumption; check current model prices including output and reasoning yourself.
4. Select **Show estimate**. Mailhelp states the typical estimate and the worst
   case in tokens and USD. If the budget is not sufficient, the required minimum amount is shown there.
   Mailbox, folders, number, price, and budget remain in the form. The listed
   models come from the configuration; the price cap remains your manual assumption.
5. Select **Start read-only learning run (chargeable)**. For 20 mails, depending on the model,
   a budget of about 1 USD is typically sufficient.

During the run, the page shows “Running: … mails checked, … errors”. You control it with **Pause**,
**Resume**, and **Cancel**. The budget is checked before every AI call;
the run stops before it would be exceeded. If the configuration has been changed since the start,
the run cannot be resumed; a new learning run replaces it.

### Check and take result <!-- mailhelp-id:bedienung/ergebnis-pruefen-und-uebernehmen -->

After the run, **Topics, exclusions and evidence** show per suggestion the title, description, the
evidence from the Mails and the senders:

- **Takeover:** **Do not take**, **Topic** (relevant, `topics.yaml`) or **Exclusion topic**
   (irrelevant, `irrelevant_topics.yaml`).
- **For all mailboxes** takes the topic globally instead of only for the selected mailbox.
- **Ignore senders for exclusion topic** additionally sets the senders for an exclusion topic
   to the list of ignored senders (`irrelevant-senders.json`).
- **Save selection as draft** remembers the decision per suggestion.

Under **Additional retrieval folders** you select folders that will also be retrieved in the future
(**Save folder selection**). Only **Explicitly take selected topics, filters and folders**
writes everything together into the configuration; **Dismiss** discards the result.
Afterwards select **Reload configuration** so that email retrieval uses the new topics.

### Learning Mode in the Terminal and Settings <!-- mailhelp-id:bedienung/lernmodus-im-terminal-und-einstellungen -->

Alternatively, the learning mode runs interactively in the terminal. This command reads 20 Mails and prompts for the topics one after another:

```sh
mailhelp --learn 20 --mailbox 1 --config-directory .
```

With multiple mailboxes, `--mailbox NUMMER` or `--mailbox alle` is required. In Docker, `compose.learn.yaml` with writable configuration is provided for this.

Under **Settings → AI and Statistics**, `learning.parallel_llm_calls` (simultaneous AI calls in learning mode, default 4) and `learning.decision_llm_content` are available for this.

### Learning data <!-- mailhelp-id:bedienung/lernbestand -->

Regardless of the learning mode, Mailhelp stores every manual decision about a suggestion with Email, AI results, original and decided suggestion in the learning data (`data/<Betriebsart>/learning/decisions.jsonl`). It is the material for [Learning from decisions](#aus-entscheidungen-lernen); Mailhelp does not thereby change its topics or decisions independently, but only after your approval and confirmation. Complete AI requests and responses are added only with `learning.decision_llm_content`. Retention is governed by `retention.decision_learning_days` (default unlimited).

### Learning from decisions <!-- mailhelp-id:bedienung/aus-entscheidungen-lernen -->

You can find rule learning under Learning: choose “Open learning from decisions”
(`/lernen/entscheidungen`). The
topic management (Settings → Topics) also links to this page. This function uses the
decisions already logged; it does not retrieve any Mails. The function requires the
prompt block `decision_rule_learning` in `prompts.yaml`. For older installations, take the block
from the supplied example and reload the prompt configuration as usual.

1. Under “Which decisions?” choose: **Only new decisions since the last analysis**
   (default, at most 100) or **All previous usable decisions** (at most 500,
   more evidence and higher costs). The current count is shown behind each option. If there are no
   new ones, choose “All previous”. Read the note about data transfer and possible costs. Choose only after checking the
   explicit approval “Analyze decisions”. Limited excerpts and
   corrections are transmitted to the active AI provider. Without approval, no call is made.
2. After completion, read the summary at the top; the links jump to the individual
   Proposals. It also states how many similar rejections were sent to the AI
   only as a count. In each card, “Previous rule and proposal” shows only the changed fields;
   new and removed examples are marked with “+ new” and “− removed”, unchanged fields
   are opened by “Show unchanged fields”. “Decision evidence” lists Subject, Decision and Date; the
   excerpt opens with “Show excerpt”. A rejected Task does not automatically make
   its Email irrelevant; “already done” remains a positive example.
3. Change name, Description, examples, exclusions and activation as needed. Examples
   and exclusions are listed individually, one per line. Existing topic IDs and mailbox areas remain
   stable. Optionally, under “Edit complete topic YAML (optional)”, enter a complete
   topic; this then replaces the field values.
4. In each card, under “Decision on this proposal”, choose **Apply**, **Dismiss – do not
   propose again** or **Leave open** (default). The bar at the bottom counts
   how many are applied and how many are dismissed. Choose **Review selected changes**. The separate
   comparison **Review edited changes** shows exactly your field or YAML changes.
   Only there, check **Explicitly confirm selected rule changes** and
   choose **Apply reviewed changes**. “Continue editing” opens editing;
   then review again. A new review state replaces the previous one. Without a selection or
   with invalid YAML/schema, nothing is applied. The entries remain for correction. For externally
   changed files, resolve the conflict and start a new analysis of the current state.
5. For “Analysis failed”, the cause is shown below. After “truncated at output
   limit”, Mailhelp has already made a second, reduced attempt. Try again later
   or choose “Only new decisions”. The AI log shows the token usage and length of the truncated response for this.
6. For interrupted writing after login, explicitly confirm “Complete application”.
   Mailhelp checks all files again and completes only the already approved local
   change. It does not start a new AI call and does not overwrite third-party changes.
7. The review view lists dismissed Proposals under “Will be dismissed and not proposed
   again”. If only Proposals are dismissed, the button is called **Dismiss proposals**;
   no rule file is changed. “Leave open” saves nothing – a later run may bring the
   proposal again. At the bottom of the page, “Show previously dismissed proposals” lists all
   blocked Proposals with Date and change; **Allow again** lifts the block.
   During the next analysis, Mailhelp tells the AI which changes you rejected. If
   it still proposes the same change, Mailhelp hides it; the summary states how many
   Proposals were hidden this way. The AI may nevertheless bring a differently worded rule with the same meaning again – then simply dismiss it again.

New analyses apply relevant rules at the next safe processing point. The
exclusion topics keep their previous meaning in learning/decision test mode; for
normal mail analyses, the relevant topics and their exclusions apply. Existing
Calendar entries and Tasks are not changed by rule learning. A new analysis
replaces a still open review draft; a restart does not repeat a running AI analysis.

### Measure and improve the acceptance rate <!-- mailhelp-id:bedienung/annahmequote-messen-und-verbessern -->

Under **Learning → Proposals** (`/lernen/vorschlaege`), Mailhelp measures how many proposals you accept and how many you dismiss. The Statistics help you identify where incorrect proposals arise and how to avoid them in a targeted way.

1. **Metrics and Statistics:** Three tiles show the overall acceptance rate, for Tasks and for Events. Below them follow the history per calendar week, sortable tables by topic and by sender, and a breakdown of dismissal reasons. The time range can be filtered via the dropdown (e.g. 30, 90 days or Entire time range).
2. **Reasons for dismissals:** After dismissing a proposal (on the web on the result card or in Telegram), Mailhelp optionally asks “Dismissed. Why?”. Five fixed reasons are available: “Does not concern me”, “For information only”, “Advertising or newsletter”, “Misrecognised (date, content)” and “Other reason”. The field is never mandatory; Dismiss remains a single step. One click saves the reason, which flows into Statistics and as a feature into rule learning.
3. **Sender notices:** If a sender causes a conspicuously high number of incorrect proposals (at least 5 decided proposals in 90 days with an acceptance rate of no more than 10%), a notice appears on the Statistics page and the result card. “View” opens a preview of all stored Mails from this sender with accepted proposals marked. By pressing a button, the Address can be added to the sender prefilter after explicit confirmation. “Do not suggest again” hides the notice; previously dismissed notices can be allowed again at any time in the overview.
4. **Notice about rule learning run:** If at least 20 new dismissals have occurred since the last rule learning run, Mailhelp recommends a new learning run at the top of “Open” and “Learning” in order to refine your topic rules. The notice appears at most once per week and can be paused for seven days with “Hide”.

## Sender rules and prefilter <!-- mailhelp-id:bedienung/absender-regeln-und-vorfilter -->

Under **Settings → Sender rules** (`/einstellungen/absender`) you specify which Mails Mailhelp classifies already before every AI call. As of 7.7, there are three kinds:

- **Ignore:** Mails are classified as irrelevant without an AI call and without notification – for an Address (`newsletter@shop.de`), a Domain with all subdomains (`shop.de`), a Pattern with `*` (`no-reply@*`), or a Subject (`Automatische Antwort:`).
- **VIP – always relevant:** Mails count as relevant without a relevance check, even if a block matches. The Events and Tasks from them still require your confirmation; a VIP only saves the relevance check.
- **Exception only:** lifts any block for a sender without making them a VIP. Previous Mailbox Exceptions are listed here and can be converted with “Make VIP”.

You first check a new rule with **Check matches**: Mailhelp counts how many of the last 200 Mails it would have matched, and warns for Domains of large email providers. Only then does **Save rule** appear. Each rule shows matches and last match and can be switched off and on again.

On an Email you find next to the sender **Ignore sender**, “Ignore domain …” (with the name of the Domain) and **Mark as VIP**. If Telegram asks whether an Email is relevant, the button 🚫 **Always ignore sender** ignores the sender in future; **Undo** only removes this rule again. Which rule classified an Email is shown under “How this Email was processed”.

The **Header prefilter** detects automatic system Mails (`Auto-Submitted`, `Precedence`) and newsletters (`List-Id`, `List-Unsubscribe`). Both filters are initially off. In the **Trial**, the AI still decides; Mailhelp only counts how many Mails would have been filtered out. Circulars that you want to keep, you enter as a **Distribution list exception** (e.g. `<eltern.schule.de>`).

**Learning → Proposals** suggests new rules from your decisions: senders whose Mails the AI repeatedly classified as irrelevant, and senders whose Mails always led to confirmed Proposals. **Statistics** shows in the “Prefilter” section how many relevance checks were omitted, and estimates the savings from the real checks in the same Time range.

## Operation on the phone <!-- mailhelp-id:bedienung/bedienung-auf-dem-telefon -->

On the phone, only the Quick filters are at the top; **Search and sort** expands Search, Sort order and grouping. The bar at the bottom leads to **Open**, **Mails**, **Review** and **History**; **Status** and the remaining areas are under **More**.

On phone and tablet, you can decide cards with swipe gestures (see [Swiping on the phone](#wischen-auf-dem-telefon)).

## Language <!-- mailhelp-id:bedienung/sprache -->

The “English” or “Deutsch” link at the end of the navigation changes the interface language for
this browser. The language cookie retains the choice for one year. Without a saved choice, Mailhelp
uses the supported browser language with the highest quality weight, then `language` from
`config.yaml`. The web interface, Help, JavaScript messages and offline pages support both languages.
Original emails and user-written text retain their wording. Normal email analysis continues to use
the configured prompts; changing language does not start another analysis.

Open `/de/` or `/en/` to choose the demo language before starting. Both corpora contain 30 synthetic
emails and proposals ready for confirmation. Switching language changes the interface and retains
your decisions and current corpus. A confirmed restart loads the corpus in the selected language.
Restart requires confirmation, affects only your session and invalidates previous forms.

`mailhelp --language en --help` shows English CLI help without configuration or service access.
`--language` applies to the individual invocation and can also be used with `--demo`.

## Connection problems <!-- mailhelp-id:bedienung/verbindungsprobleme -->

If a connected service refuses the sign-in, a notice “Connection problems” appears above **Open** and **Emails**. It names the service and mailbox or target profile, the effect (for example “Calendar sync and calendar changes are not possible at the moment.”), the time of the last failed check and the link **Check connection** to the matching settings page. Mailhelp does not claim “expired” when the service only reports a refusal.

The notice stays visible with filters, reloads and restarts and cannot be dismissed. It disappears only once the same service has been reached successfully again; saving new credentials alone is not enough. An open page shows new notices and their removal after at most 15 seconds. Timeouts and network errors do not count as sign-in problems. Mailhelp checks connected services read-only at start and then every 15 minutes.

### Connecting Google through Inboxstride <!-- mailhelp-id:bedienung/google-ueber-inboxstride-verbinden -->

In a hosted Inboxstride instance you connect Google Calendar without client data or tokens of your own. In the initial setup (step “Calendar and tasks”) and under **Settings → Target profiles**, **Connect with Google** leads to Google. There you choose your account and allow calendar access. Back at Inboxstride you continue with **Choose calendar**, pick a calendar with write access and confirm with **Adopt connection**. Only then does the new connection apply; until then a previous one stays unchanged, also after a cancellation or an error.

The connection itself creates no events. When the account changes, open proposals of this profile need a new confirmation. If Google later refuses the access, the “Connection problems” notice leads straight to **Reconnect Google**. Google Tasks remains reserved for self-hosting with an own Google client.

Once a connection exists, the same page offers **Choose another calendar**: Inboxstride reads the calendars with write access through the existing access, without a new Google sign-in, and **Adopt calendar** saves the choice. **Disconnect** stops issuing tokens for this profile at once, also for an access still cached. Events already created stay, other profiles stay connected, and the grant at Google itself is not revoked; you can do that in the security settings of your Google account if needed. Afterwards **Reconnect Google** leads to a new connection.

## Failed Mails <!-- mailhelp-id:bedienung/fehlgeschlagene-mails -->

The Status page shows under “Recent errors and action required” which Email is being retried or has been given up. **Failed emails** opens the error list (`/mails?state=failed`): Each row states cause, processing stage, and number of failed attempts and offers **Try again**, **Ignore**, and **Details** directly; after the action you return to the list and see the result. **Try again** starts the continuation at the next retrieval and resets the previous attempts; until then the Email appears in the list as “Retry requested”. **Ignore** (called File until 7.3) ends it as not processed and files it away; the Email remains in the archive and disappears from the error list.

On the Email page, an error appears at the very top in the “Processing errors” section with stage, cause, recommendation, state of retry, and the same buttons. **Show error report** expands all details: timestamps, field paths, and model call IDs. **Copy report** places the report as text in the clipboard, for example for troubleshooting; it contains no Email text, no addresses, and no access data. In the error list, **Details** opens the same report as a dialog.

Above the error list are **Try all again** and **Ignore all**. A confirmation page first states the number of affected Mails; only there is the action triggered. Afterwards the list reports how many Mails were queued. Mails that have changed in the meantime or are already queued are skipped. “Try all again” omits Mails without analysis data and already requested retries. Both buttons only change the stored state. A new Event or a Task still requires its own confirmation of the suggestion.

### Help with Settings <!-- mailhelp-id:bedienung/hilfe-beim-einstellen -->

The chat icon at the bottom right opens **Settings Help** as a small window over the current Settings page. “Ask about this” adopts the reference for a setting without overwriting an existing question draft. Enter a question and select **Send question**. The answer first appears in short form; **Show detailed answer** displays all steps.
While the answer is being generated, you can search, edit Values, and confirm and save changes. The chat remains open; answers do not reload the Settings page.

Sources open in the window; **Back to conversation** returns to the same place in the History. Even after changing pages, reloading, or reopening, the conversation remains at the last-read position; if you read at the very bottom, you see new answers automatically. Drag the header (or focus the title and use the arrow keys) to reveal hidden Settings. Drag at an edge or corner for more space (by keyboard, Shift+Arrow keys on the title); the size is retained when changing pages.
**Close help chat** hides the window. When reopened, the conversation and draft are still present as long as the session and retention apply. **Clear chat** discards the contents and keeps the window open. Mailhelp automatically saves the unsent question as you type; without JavaScript, new answers appear on the next page load. The chat only explains and does not itself change any data.

### Page overview <!-- mailhelp-id:bedienung/seitenuebersicht -->

Lists (history, emails and analytics) have a toolbar at the top: search and the main selectors share a row with the primary action. Additional filters are under **More filters**, together with the number currently active. **Reset** appears when a filter is applied. Filters are included in the address, so bookmarks retain them.
Emails, history and proposal matching show one row per item: title, sender and time, with a status badge on the right. Click the title to open the email or proposal.

| Page | Contents |
| --- | --- |
| **History** | Every change and decision with its version; filter by search, status and type, or by event and period under **More filters** |
| **Briefing** | Daily overview of open decisions and events |
| **Topics** | What counts as relevant (Settings → Topics): overview, search and editing with a preview |
| **Learning** | Learn from the mailbox and improve rules using decisions |
| **Analytics** | Costs, durations and charts of AI calls |
| **Status** | Last contact with each service and current stage; click a metric to open the corresponding overview |

On **Status**, click one of the four metrics to open its entries. **Open proposals** and **Relevance questions** lead to separate overviews with details for each proposal or email. **Failed emails** opens the email archive with the failed filter. **Queued web actions** shows the queue with links to your individual actions. Other sessions are listed without private content. The overview remains accessible with zero entries. “Refresh overview” loads the latest state; opening or refreshing it does not execute any action.
Below this is the number of emails Mailhelp has fully processed so far, including irrelevant and duplicate emails. Telegram `/status` starts with the same number. An email is briefly excluded from the count while it is being analysed again.

### Statistics <!-- mailhelp-id:bedienung/auswertung -->

At the top, the key figures are shown as tiles; a click opens the matching calls. The links above them jump to charts, flow, and the table “By model and stage”. On the phone, the charts are collapsed (**History and Distribution** opens them). If no calls were recorded in the time range, only a note is shown there.

**Statistics** shows costs and times of the AI calls for the selected time range. Durations appear in the matching unit, for example `4 Min. 12 s`, `20 Std. 54 Min.` or `3 Tage 4 Std.`; for the summed call duration, the exact seconds are shown in parentheses after it. The summed call duration adds all attempts, including parallel ones, and is not an end-to-end time.

The cost chart shows a dashed average line and, from 14 days, a 7-day average. The **Call duration** is a scatter plot: each point is a call, crosses are errors, the line is the median per day. **Compute time per processing stage** states the share and duration of each stage; the **email processing flow** shows all stages in their order and marks the longest waiting time; local stages are called “local · not measured”.

Every Value in the fact table is a link. It opens the call list with the matching preset, for example only the failed calls with their cause, the most expensive, or the longest. Status and sort order can be changed there; “← Back to Statistics” retains the filter. Individual calls are available only for the retention period of the metrics (default 90 days).

Mailhelp measures every processing stage, not only the AI calls. The fact table states the **end-to-end time per email** (without the time in which an email waits for your decision; this is shown below). “Time per processing stage” shows how much time each stage actually takes; the flow plan states duration and AI share for each stage (“of which AI”) and marks the longest waiting time. “Preparation in detail” divides preparation into parsing, attachments, and image recognition. A click on a stage under “Slowest runs” shows the slowest emails of this stage. On **Status**, for the running stage, it states how long it usually takes.

Mailhelp only places reply drafts in the Drafts folder; it never sends emails.

## Web Push from 6.8.1 <!-- mailhelp-id:bedienung/web-push-ab-681 -->

The Settings show nine check levels for the signed-in device. On iOS, open Mailhelp from the Home screen as an installed web app via HTTPS. Turn on Server Push under Setup, enter a valid VAPID contact and restart. Then activate the device. Missing Mailbox channels can be added after an explicit, version-checked preview.

A test push transmits exclusively a fixed neutral type. Provider acceptance and device feedback are separate states; the visible system message must be checked on the device. After a key change or 401/403, reactivate. 429, 5xx and network errors remain repeatable. Own changes and Proposals open before activation do not generate a new push. Save subscriptions, VAPID, activation times and version origin in the persistent data directory. Details: [Release 6.8](../archiv/Release-6.8.md).
