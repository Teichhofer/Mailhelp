# Troubleshooting <!-- mailhelp-id:fehlerbehebung/fehler-beheben -->

Reviewed for Mailhelp 7.0. Safe next steps for common problems. None of these steps creates duplicate entries: Mailhelp never repeats a write whose outcome is unclear; it reconciles it with the provider first.

| Situation | Cause | Next step |
| --- | --- | --- |
| Mailbox sign-in failed | Incorrect username, password or connection type | Check **Settings → Credentials**; use an app password with two-factor authentication; **Check access** |
| Folder missing | Folder name differs from the server | Use the discovered folder list on the mailbox page |
| Google sign-in expired (`token_refresh_denied` in the log) | Refresh token revoked or expired | Run **Connect Google** again |
| Microsoft sign-in refused | Token expired | **Connect Microsoft** or `mailhelp --microsoft-login` |
| Provider unreachable | Network problem or provider outage | Wait; Mailhelp retries. **Status** shows the last contact |
| AI budget exhausted | `limits.llm_calls_per_minute` reached | No action needed: the email will be analysed automatically later |
| “The message exceeds a safety limit” | Email too large or deeply nested | Raise the `limits` only for trusted emails |
| Setting “saved – takes effect after a restart” | Not active yet | **Settings → Restart Mailhelp** |
| Creation not yet verified | Entry not visible at the provider or read access refused | Inspect the entry at the provider, then **Check again** |
| Unclear write outcome | Provider response was lost | No action needed: Mailhelp reconciles and does not create the entry again |
| Target changed, creation blocked | Proposal confirmed for a different target | Restore the original target or confirm the new proposal |
| “Shutdown not performed” or “Restart not performed” | Confirmation belongs to an earlier startup or is incomplete | Confirm again on the same page; if that fails, stop Mailhelp in its terminal with Ctrl+C |
| “Mailhelp is already running …” | Second startup using the same data directory | Stop the running instance |
| Forgotten web password | – | On the host, run `mailhelp --reset-web-password --config-directory .` |

## Email repeatedly fails to process <!-- mailhelp-id:fehlerbehebung/mail-wird-wiederholt-nicht-verarbeitet -->

The status page lists affected emails with the start time, stage, attempt count and next attempt. “Abandoned” means Mailhelp has suspended automatic processing. Open the email and fix the cause first. “Retry” resets the attempt count and waiting period. “Ignore” deliberately ends processing; the email stays visible in the archive as unprocessed and no longer counts as requiring attention.
This cannot restore analysis data already removed; in that case only Ignore is available. Both actions are also available directly in the error list (`/mails?state=failed`). Neither creates events or tasks.

## Analysis data removed by retention <!-- mailhelp-id:fehlerbehebung/analyse-daten-nach-aufbewahrung-entfernt -->

“Action detection cannot be resumed – analysis data removed by retention” means a completed email has a failed action-detection stage whose required analysis results have since been removed. Mailhelp ends automatic resumption once, with `resume_abandoned`. The email remains visible in the archive under the failed filter. If you want it analysed again, explicitly start a reanalysis.

## Resetting the web password <!-- mailhelp-id:fehlerbehebung/web-passwort-zuruecksetzen -->

1. Stop the running service cleanly; the reset command requires exclusive access to the data directory.
2. On the host, run `mailhelp --reset-web-password --config-directory .` in the configuration directory. This deletes the existing password hash and signs out all web sessions; it does not generate a new password.
3. While the service is stopped, run `mailhelp --pair --config-directory .` and keep the one-time terminal code ready. Restart the service and sign in with this code.
4. After successful sign-in, explicitly set a new web password at `/einstellungen/web-passwort` if desired. Never enter the code or password in the help chat.

## Diagnostics <!-- mailhelp-id:fehlerbehebung/diagnose -->

**Settings → Check connections** tests each connection without writing and gives a result and recommended action per service. **Check everything (self-test)** on the same page tests all components. The diagnostic report contains no credentials. Logs are in the log directory (`logging.directory`); AI request contents are logged only when explicitly enabled.

## Help chat in the settings window <!-- mailhelp-id:fehlerbehebung/hilfschat-im-einstellungsfenster -->

The window stays open while searching or saving. If it is in the way, drag its header, or focus the title and use the arrow keys. Only **Close help chat** hides it; **Clear chat** removes the conversation. If an answer does not appear, reload the page. Do not resend a question because you changed pages: Mailhelp shows the existing job.

If browser storage is blocked, Mailhelp saves the window state on the local server before navigation. If that fails, the page retains the draft; check your connection and try again. Without JavaScript, an unsent question is not retained when changing pages. If “crypto.randomUUID is not a function” appears (Mailhelp over `http://` on the home network before 5.5), update to 5.5; since then Mailhelp can generate keys without a secure context. Sign in again after logout or session expiry; a new session does not inherit old private chat data from browser state.

## Web Push from 6.8.1 <!-- mailhelp-id:fehlerbehebung/web-push-ab-681 -->

Settings shows nine check stages for the signed-in device. On iOS, open Mailhelp from the Home Screen as an installed web app over HTTPS. Enable server push under Setup, enter a valid VAPID contact and restart. Then enable the device. Missing mailbox channels can be added after an explicit, version-checked preview.

A test push transmits only a fixed neutral type. Provider acceptance and device feedback are separate states; check the actual system notification on the device. Enable the device again after a key change or 401/403. Errors 429, 5xx and network failures remain retryable. Your own changes and proposals already open before activation do not trigger a new push. Back up subscriptions, VAPID, activation times and version provenance in the persistent data directory. Details: [Release 6.8](../archiv/Release-6.8.md).
