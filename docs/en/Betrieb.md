# Operation and updates <!-- mailhelp-id:betrieb/betrieb-und-update -->

Reviewed for Mailhelp 7.0.

## Recurring processing errors <!-- mailhelp-id:betrieb/wiederkehrende-verarbeitungsfehler -->

Mailhelp tries the same failure for an email at most five times. The intervals are 1 minute, 5 minutes, 30 minutes and 2 hours. After that, the email remains stored and is no longer picked up automatically. Permanent errors are abandoned immediately. Provider rate limits apply only their own waiting period. Status shows the stage, start, attempt count and next attempt. Telegram reports abandonment once, with a link to the email if the web interface is enabled.

`logging.verbose: false` reduces routine lines: unchanged folder counts hourly, one completion per Telegram poll, and web requests only on errors or when taking over a second. The first stack trace stays complete; repeats appear every 15 minutes with a counter. “Verbose log” enables individual messages after a restart; full LLM contents still require their own switches. The synthetic daily limit is 2 MB with unchanged rotation limits.

New state files contain optional retry fields. Before returning to an older version, these must be removed compatibly from the current state. Never blindly replace later confirmed write outcomes with an old backup.

## Starting, checking and stopping <!-- mailhelp-id:betrieb/starten-pruefen-beenden -->

| Command or page | Effect |
| --- | --- |
| `mailhelp --check --config-directory .` | Validates configuration without network access |
| `mailhelp --check-access --config-directory .` | Checks all access without writing |
| `mailhelp --config-directory .` | Starts the service |
| **Settings → Restart Mailhelp** | Controlled restart; saved changes take effect |
| **Settings → Stop Mailhelp** | Stops the service |

Only one instance runs per data directory. **Reload configuration** changes connections without restarting the process.

## Saving, activating, reloading and restarting <!-- mailhelp-id:betrieb/speichern-aktivieren-neuladen-und-neustart -->

| Step | What happens | When it takes effect |
| --- | --- | --- |
| Save | After the preview (“Review”), a changed setting is written to `config.yaml`. The page says “saved” until it takes effect. | – |
| Apply during operation | Mailhelp automatically applies settings such as polling intervals, retention, metrics, personal information, notifications, event durations, proposal matching, drafts and briefings. | At the next safe point, without a restart |
| Activate | Mailboxes, IServ accounts and target profiles are saved as drafts on their pages and activated only after another explicit confirmation (**Apply draft**, **Check connection and activate mailbox**). | Between two mailbox cycles |
| Reload configuration | **Explicitly reload configuration** applies topics, prompts, mailboxes, credentials and target profiles after unfinished analyses are complete. | At the next safe point, without restarting the process |
| Restart | **Restart Mailhelp** shuts down the service cleanly and starts it again; all other saved settings, web access and data-directory changes take effect. | Immediately after the restart |

Saving or activating never creates tasks or events; that always requires explicit confirmation of a proposal.

## Demo instance <!-- mailhelp-id:betrieb/demo-instanz -->

`mailhelp --demo --config-directory <leeres Verzeichnis>` starts a demo with 30 prepared sample emails, without a mailbox, Telegram, AI or real targets. Each visitor gets a private copy for two hours through “Start demo”; confirmations are simulated only. Port and hostnames: `MAILHELP_DEMO_PORT`, `MAILHELP_DEMO_HOST`, `MAILHELP_DEMO_ALLOWED_HOSTS`. The demo refuses directories belonging to normal installations, and vice versa.

Starts are limited to 5 per client and 60 overall per hour. Behind your own reverse proxy, set `MAILHELP_DEMO_TRUST_PROXY=1` so the client address comes from `X-Forwarded-For` (last entry; the proxy must append its peer address, as nginx, Caddy and Traefik do). Do not set the variable without a proxy, or visitors could bypass the limit with an invented header. Visitors answer clarification questions only with prepared example answers and reset their own copy through “Restart demo”. The demo automatically removes expired copies.

### Demo in a Docker container <!-- mailhelp-id:betrieb/demo-im-docker-container -->

```sh
MAILHELP_DEMO_ALLOWED_HOSTS=demo.example.org docker compose -f compose.demo.yaml up -d --build
```

`compose.demo.yaml` starts the same image entry point with `--demo` and a separate `demo-daten` volume. It does not mount the normal instance’s `.env`, `config.yaml`, data or logs. Both instances run independently, including simultaneously. The `mailhelp-demo` network is internal, so the container cannot reach the internet. This is the second protective layer: the demo does not construct clients for mailboxes, Telegram, AI or targets in the first place.

The HTTPS proxy for the demo subdomain joins `mailhelp-demo` and forwards to `mailhelp-demo:8765`. An internal network cannot publish a port on the host. If the proxy runs on the host (for example Tailscale Serve), the service needs a normal network with `127.0.0.1:<Port>:8765`; a firewall rule for the demo network then blocks outbound traffic (on Linux in the `DOCKER-USER` chain). Keep `MAILHELP_DEMO_TRUST_PROXY` set only while the proxy is the container’s sole point of access.

To reset the entire demo, stop its container and delete the `demo-daten` volume. At the next startup the directory is empty and receives a new marker.

## Backups <!-- mailhelp-id:betrieb/sicherung -->

For a consistent backup, stop the service cleanly first. Copy the files only after it has fully stopped, then start Mailhelp again.

Back up `config.yaml`, `.env`, `prompts.yaml`, topic files, the data directory (`data_directory`, readable JSON state files) and, if needed, the log directory. `.env` contains credentials and must be kept private.

## Updating <!-- mailhelp-id:betrieb/update -->

Restart the service after installing a new version. Stylesheets and scripts are read at startup. Each page references the correct content hash for every file, even when an older service worker handles the initial request.

1. Stop Mailhelp. This is mandatory on Windows, which otherwise locks the executable.
2. Back up configuration, `.env`, prompts, topics and the data directory (see Backups).
3. Fetch the new version and install it in the same virtual environment: `python -m pip install -r requirements.lock` and `python -m pip install --no-deps -e .`.
4. Run `mailhelp --check --config-directory .`, then start the service.

New settings use their defaults without rewriting your `config.yaml`. New prompt stages are not silently inserted into a custom `prompts.yaml`; the corresponding release report explains how to adopt them.

## Retention <!-- mailhelp-id:betrieb/aufbewahrung -->

Mail content, history, diagnostics, verification records and learning logs follow the periods under `retention`; open items remain protected. Original emails in the mailbox are never deleted.

## Returning to an older version <!-- mailhelp-id:betrieb/rueckkehr-zur-vorversion -->

Before returning to a version older than 5.2.0, stop the service and run `mailhelp --prepare-rollback --config-directory .`. See the release report for the relevant version for details.

## Web Push from 6.8.1 <!-- mailhelp-id:betrieb/web-push-ab-681 -->

Settings shows nine check stages for the signed-in device. On iOS, open Mailhelp from the Home Screen as an installed web app over HTTPS. Enable server push under Setup, enter a valid VAPID contact and restart. Then enable the device. Missing mailbox channels can be added after an explicit, version-checked preview.

A test push transmits only a fixed neutral type. Provider acceptance and device feedback are separate states; check the actual system notification on the device. Enable the device again after a key change or 401/403. Errors 429, 5xx and network failures remain retryable. Your own changes and proposals already open before activation do not trigger a new push. Back up subscriptions, VAPID, activation times and version provenance in the persistent data directory. Details: [Release 6.8](../archiv/Release-6.8.md).
