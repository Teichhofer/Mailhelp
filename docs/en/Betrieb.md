# Operation and updates <!-- mailhelp-id:betrieb/betrieb-und-update -->

Reviewed for Mailhelp 7.0.

Server changes also follow the documentation requirement in [AGENTS.md](../../AGENTS.md).
Once setup, a change or a repair has been verified as successful, update the confirmed
state, reproducible steps, affected versions, checks and rollback procedure before
reporting the work complete. This includes DNS, nginx, TLS, containers, systemd,
firewall rules, file permissions, backups and OAuth configuration. Clearly label
failed or reverted attempts rather than describing them as the active setup.
Keep secrets outside Git.

[Version 8.0 planning](../Planung-8.0.md) requires a version-controlled server handbook
at docs/Serverhandbuch.md (planned) and secret-free templates under `ops/server/`.
The full rebuild and recovery guide still needs to be created. Until then, record
the verified operational state in the operating documentation. Local notes and
server-only configuration files do not replace a Git-backed source of truth.

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

### Language entry points behind the proxy (verified on 18 Nov 2026 with 7.8.1) <!-- mailhelp-id:betrieb/sprach-einstiege-hinter-dem-proxy-verifiziert-am-18112026-mit-781 -->

Since 7.8.1, Mailhelp serves `/de/`, `/en/` and `/sprache?wert=de|en` itself. The answer is a redirect (303) to the start page with the cookie `mailhelp_lang` (`Secure`, `SameSite=Lax`, one year); an invalid value returns 400. The proxy therefore passes these paths through unchanged and sets neither a language cookie nor a redirect of its own.

Switching an existing proxy configuration:

1. Check at the container without the proxy that `/en/` answers 303 with `Set-Cookie: mailhelp_lang=en`.
2. Back up the configuration file of the demo subdomain.
3. Remove the mappings for the language cookie and the cache header, the two `add_header` lines for them and the blocks `location = /de/` and `location = /en/`.
4. Run `nginx -t` and only on success `systemctl reload nginx`; otherwise restore the backup.
5. Check over HTTPS: `/en/` with a German browser shows the English start page, `/de/` with an English browser the German one; a demo start shows the matching sample data.

Way back: copy the backed-up file back, `nginx -t`, `systemctl reload nginx`. Versions before 7.8.1 need the proxy redirect because they do not know `/de/` and `/en/`.

### Server update with an image (verified on 18 Nov 2026, 7.7.6 → 7.8.1) <!-- mailhelp-id:betrieb/server-update-mit-image-verifiziert-am-18112026-776-781 -->

The productive instance and the demo run as Compose projects of the same image. The update ran as follows:

1. Create a source archive of one commit: `git archive <commit> Dockerfile README.md pyproject.toml requirements.lock src`; on the server, unpack it into its own release directory `<version>-<commit>` and build the image `mailhelp-production:<version>-<commit>` from it.
2. Check the version in the image without network: `docker run --rm --network none --entrypoint python <image> -c "import mailhelp; print(mailhelp.__version__)"`.
3. Back up both Compose files, replace image and build path in them and check them with `docker compose config --quiet`.
4. Stop both containers (production with a 45-second grace period), only then archive the runtime directories of both instances; this gives a consistent state.
5. Start both containers without rebuilding, wait for the health checks and check the version in the running container. If a step fails, the backed-up Compose files are written back and the previous containers are started again.

Result on 18 Nov 2026: both health checks passed, version 7.8.1 in both containers, existing demo visitors were taken over without errors. Way back: copy the backed-up Compose files back, restore the backed-up runtime archives with the containers stopped and start the containers with the previous image, which is still present. Credentials stay in the instance's `.env` and are taken over neither into the source archive nor into the image.

Observation after the restart: Google refused to renew the calendar access (HTTP 400) because the refresh token of an OAuth app in the Google status `Testing` expires after seven days. The remedy is a new Google sign-in through the web interface; switching the app to the Google status `In production` helps permanently.

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
