# Postfach-OAuth für Inboxstride 8.1

Stand: 20.11.2026. Implementierungs- und Freigabeanleitung, noch keine bestätigte
Produktivkonfiguration. Der Betreiber hat bestätigt, dass Gmail-IMAP-Freigabe und
Microsoft-App-Registrierung noch fehlen. Der Kalenderzugang aus 8.0 bleibt getrennt.

## Google

IMAP benötigt `https://mail.google.com/`; die Kalenderberechtigungen genügen nicht.
Vor Freischaltung in der Google-Console den Mail-Scope, die notwendigen
Verifizierungs-/gegebenenfalls Sicherheitsprüfungen und den tatsächlichen Datenfluss
mit OpenRouter abgleichen. Nicht ungeprüft als öffentlich freigegeben markieren.
Der bestehende Google-Webclient verwendet weiterhin ausschließlich den vereinbarten
Callback `https://auth.inboxstride.de/auth/google/callback`.

Erst nach Anbieterfreigabe und entsprechender Aktualisierung der öffentlichen
Anwendungsinformationen im Auth-Dienst `INBOXSTRIDE_AUTH_GMAIL_ENABLED=1` setzen und
den Dienst kontrolliert neu starten. Standard ist deaktiviert; ein manuelles
Anhängen von Mail-Scopes an Kalenderverbindungen ist nicht vorgesehen.

## Microsoft

In Microsoft Entra eine separate Webanwendung für Inboxstride-Postfachzugriff
registrieren. Bei Unterstützung privater Outlook.com-Konten und Microsoft-365-Konten
den passenden Kontotyp für Organisationen und persönliche Microsoft-Konten wählen.
Redirect: `https://auth.inboxstride.de/auth/microsoft/callback`.

Delegierte Exchange-Online-Berechtigung `IMAP.AccessAsUser.All` und `offline_access`
verwenden. Keine Graph-Kalender-, SMTP- oder anwendungsweiten Mailboxrechte ergänzen.
IMAP muss im Zielpostfach erlaubt sein; Organisationsrichtlinien und notwendige
Administratorzustimmung vor dem Pilot prüfen. Client-Secret mit dokumentierter
Laufzeit erstellen und rechtzeitig erneuern.

Private JSON-Datei mit diesen Schlüsseln außerhalb von Git vorbereiten:

```json
{
  "client_id": "APP-REGISTRIERUNGS-ID",
  "client_secret": "PRIVATES-CLIENT-SECRET",
  "tenant": "common"
}
```

`common` unterstützt die konfigurierten privaten/organisatorischen Kontotypen;
alternativ `organizations`, `consumers` oder eine konkrete Mandanten-ID verwenden.
Die App-Registrierung und Mandantenrichtlinien müssen dazu passen. Die Datei privat
mit Modus 0600 bereitstellen, im Auth-Container nur lesbar einhängen und importieren:

```sh
docker compose -p inboxstride-auth -f /opt/inboxstride-auth/compose.yaml stop auth
docker compose -p inboxstride-auth -f /opt/inboxstride-auth/compose.yaml run --rm --no-deps \
  -v /privater/pfad/microsoft-imap.json:/run/microsoft-imap.json:ro \
  auth set-mail-client /run/microsoft-imap.json
docker compose -p inboxstride-auth -f /opt/inboxstride-auth/compose.yaml up -d auth
```

Dateipfad und Leserechte für UID 65532 passend zur Installation setzen. Der Import
speichert die Werte verschlüsselt im vorhandenen Secret-Store. Private Importdatei
anschließend aus dem temporären Bereitstellungspfad entfernen und den Dienst neu
starten. Niemals die JSON-Werte oder entschlüsselte Zustände in Logs ausgeben.
Bestehende Tokens von Microsoft-Kalender oder To Do werden nicht übernommen.

## nginx und Erreichbarkeit

Zusätzlich zum vorhandenen Google-Callback ausschließlich den exakten Microsoft-
Callback an Loopback-Port 8780 weiterreichen. Dieselben Rate-Limits, GET-Beschränkung,
TLS- und Logregeln wie beim Google-Callback verwenden. Interne API-Pfade bleiben
öffentlich gesperrt. Vor Reload `nginx -t`, danach HTTPS, Header und Ablehnung
fehlender/mehrfacher State-Parameter prüfen. Callback-Querystrings nicht loggen.
Diese Erweiterung darf erst nach Prüfung als tatsächlicher Serverstand dokumentiert
werden; die bisherige verifizierte nginx-Vorlage bleibt der 8.0-Bestand.

## Pilot, Wiederverbindung und Rückkehr

Im eigenen Betrieb kann `INBOXSTRIDE_AUTH_PUBLIC_URL` die eigene HTTPS-Callback-Origin
festlegen. Beide Callback-URIs müssen exakt beim jeweiligen Anbieter registriert sein.
HTTP ist ausschließlich für localhost/127.0.0.1 vorgesehen. Die Nutzerinstanz braucht
weiterhin ihren registrierten HTTPS-Host und ihre mTLS-Identität. Der bestehende reine
Loopback-Desktopablauf für Kalender wird dadurch nicht verändert.

Die interne mTLS-Route `/intern/providers` nennt nur freigeschaltete Postfachanbieter.
Ohne Freischaltung zeigt die Oberfläche einen kontrollierten Fehler statt eines
unvollständigen Anmeldevorgangs. Für den Pilot im Postfachschritt anmelden, die
vorhandenen Ordner lesend prüfen und ausdrücklich übernehmen. Keine Testnachrichten
erstellen, keine Flags verändern, keine Kalender-/Todoist-Aktion auslösen.

Freigabe an Instanz, Sitzung, Postfach-ID, Einrichtungsstand und Zweck binden.
Kalenderzugänge bleiben eigenständig. Nach erfolgreichem Wechsel prüfen, dass nur
der betroffene IMAP-Reader ersetzt wird und vorhandene UID-Checkpoints weitergelten.
Token-Erneuerung, Widerruf und erneute Anmeldung mit einem synthetischen Dienst
testen; echte Anbieterfreigaben werden durch diese Tests nicht ersetzt.

Vor Update passenden Zustand einschließlich Secret-Store, Schlüssel und privater
CA sichern. Nach neuen Postfach-OAuth-Feldern keine alte Version starten, die diese
Konfiguration nicht lesen kann. Rückkehr zur alten Anwendung nur mit expliziter
Rückkehr der betroffenen Kontokonfiguration und nach Abgleich neuerer Schreibnachweise;
keine alten Kalender-Ledger über aktuelle Daten kopieren.

Nach erfolgreicher Serveränderung Handbuch, Vorlagen, Betriebsnachweis und Kopie
unter `/opt/mailhelp/server-docs` gemeinsam nachführen; neue Secrets bleiben im
privaten Backup, niemals im Dokumentationsbestand.

Primärquellen: [Google XOAUTH2](https://developers.google.com/workspace/gmail/imap/xoauth2-protocol),
[Microsoft IMAP-OAuth](https://learn.microsoft.com/en-us/exchange/client-developer/legacy-protocols/how-to-authenticate-an-imap-pop-smtp-application-by-using-oauth/).
