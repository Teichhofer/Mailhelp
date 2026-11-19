# Bildmotive und Schrift

Die beiden Motive wurden mit dem eingebauten Imagegen-Werkzeug über den
[Imagegen-Skill](C:/Users/User/.codex/skills/.system/imagegen/SKILL.md) erzeugt.
Die PNG-Originale bleiben im Codex-Bildverzeichnis. Für die Website wurden
komprimierte WebP-Dateien gespeichert. Der Build erzeugt zusätzlich Dateinamen
mit Inhaltsprüfsummen für das Browser-Caching.

## Workspace

Gespeichert unter `public/assets/workspace.webp` und `public/assets/workspace-small.webp`.

Verwendeter Prompt

> Use case: photorealistic-natural. Asset type: editorial photograph for a modern bilingual landing page for Inboxstride, an email-to-tasks-and-calendar assistant. Create a premium natural photograph of a quiet, considered home workspace in soft morning sunlight, warm ivory desk, slim dark laptop with an unobtrusive blank warm-white screen, a small notebook with no legible writing, ceramic espresso cup, leafy olive plant at edge, a hand resting naturally near trackpad. Composition landscape 4:3, three-quarter view, elegant large areas of breathing room, believable materials and soft shadow, forest green and warm cream accents. Photographic, calm and human, not a corporate stock photo. No text, no logos, no watermarks, no UI labels. This is an atmospheric supporting photograph, not a screenshot.

## Workflow

Gespeichert unter `public/assets/workflow.webp`.

Verwendeter Prompt

> Use case: stylized-concept. Asset type: restrained 3D editorial artwork for Inboxstride email automation landing page. A beautiful open ivory paper envelope with two clean paper cards gently rising from it, one card with a simple embossed forest-green check mark and one with an abstract small calendar grid of unlabelled squares. Warm off-white seamless background, subtle dark forest green and pale lime accents, matte paper and ceramic materials, soft directional natural studio light and realistic contact shadows. Sophisticated minimal product visualization, generous negative space, slight isometric three-quarter perspective, square composition. No text, no letters, no numbers, no logos, no glossy neon, no busy elements, no watermark.

## Schrift und Grafiken

DM Sans wird als lokale WOFF2-Datei ausgeliefert. Die Schrift stammt aus Google
Fonts und steht unter der mitgelieferten SIL Open Font License. Besucher rufen
keinen externen Font-Dienst auf.

Die Wortmarke, einfachen Symbole und Ablaufgrafiken sind direkt in HTML, CSS und
SVG umgesetzt. Produkttexte und Kartenbeschriftungen stehen in beiden Sprachen
als echter Text in der Website.

## Video vom Auftraggeber (16. November 2026)

Quelle: `gemini_generated_video_fa6be3aa.mp4`, vom Auftraggeber zur Einbindung bereitgestellt. SHA-256 Original: `cb13bfd8f1a347b6d0608b39bbe47e97f9e5a9fd649c2e5c9028df1505330cb8`.

10,03 Sekunden, 1280×720, H.264/AAC. `inboxstride-film.mp4` wurde mit FFmpeg verlustfrei umgepackt (`-c copy -movflags +faststart -map_metadata -1`); keine erneute Kodierung. Das WebP-Poster wurde bei 2,5 Sekunden erzeugt, 960×540. Der Clip ist als KI-generierte Illustration gekennzeichnet und wird lokal mit manueller Wiedergabesteuerung ausgeliefert.

## Laptopfoto mit Demo-Oberfläche, korrigierte Fassung

`design/workspace-screen-v2.png` ist die vom Auftraggeber ausgewählte korrigierte Compositing-Fassung. Das eingebaute Bildwerkzeug hat das ursprüngliche Foto mit einem Screenshot der echten laufenden Demo (synthetische Daten) kombiniert. Der vollständige Bearbeitungsprompt steht in `design/workspace-screen-v2-prompt.txt`.

Für die Website werden `workspace-screen-v2.webp` (1080×810) und `workspace-screen-v2-small.webp` (640×480) verwendet. Nur Größe und Format wurden für die Auslieferung optimiert. Beide Sprachfassungen und die Vorschau-Metadaten verweisen auf diese neuen, beim Build mit Inhaltsprüfsummen versehenen Dateien.
