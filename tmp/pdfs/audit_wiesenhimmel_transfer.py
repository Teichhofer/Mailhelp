import csv
import hashlib
import json
import statistics
import zipfile
from pathlib import Path

import pdfplumber
from pypdf import PdfReader

root = Path.cwd()
folder = root / 'output/analysis/wiesenhimmel-reelideen-2026-10-31'
pdf = root / 'output/pdf/wiesenhimmel-reelideen-winter-aus-raus-2026-10-31.pdf'
data = json.loads((folder / 'ideen-mit-belegen.json').read_text(encoding='utf-8'))
provenance = json.loads((folder / 'quellnachweise.json').read_text(encoding='utf-8'))
source = json.loads((root / 'downloads/instagram/analysis/winter-20261031/winter-posts-classified.json').read_text(encoding='utf-8'))
by_id = {str(r['id']): r for r in source}
ideas = data['ideas']
assert len(ideas) == len({i['reference_id'] for i in ideas}) == 12
assert len(source) == 472
for item in ideas:
    ref = item['reference']
    original = by_id[item['reference_id']]
    assert original['format'] == 'Video / Reel'
    assert original['calendar_month'] in (11, 12, 1, 2)
    assert original['eligible'] and not original['special_mechanism'] and not original['coauthored']
    peers = [r for r in source if r['format'] == 'Video / Reel' and r['winter'] == ref['winter'] and r['eligible']]
    median = statistics.median(r['interactions'] for r in peers)
    assert len(peers) == ref['winter_baseline_n'] >= 10
    assert median == ref['winter_baseline']
    assert ref['likes'] + ref['comments'] == ref['interactions'] == original['interactions']
    assert ref['interactions'] / median == ref['winter_index'] > 1
    assert ref['url'] == original['url'] and ref['date'] == original['date']
for path, digest in provenance['inputs'].items():
    assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest
assert hashlib.sha256(Path(provenance['offer_pdf']).read_bytes()).hexdigest() == provenance['offer_sha256']
assert all(scale == 1 for scale in provenance['card_scales'])
with (folder / '12-reelideen-mit-raus-belegen.csv').open(encoding='utf-8-sig', newline='') as handle:
    csv_rows = list(csv.DictReader(handle, delimiter=';'))
assert len(csv_rows) == 12
reader = PdfReader(pdf)
assert len(reader.pages) == 8
uris = set()
for page in reader.pages:
    assert len(page.extract_text()) > 500
    for annotation in page.get('/Annots', []):
        action = annotation.get_object().get('/A', {})
        if action.get('/URI'):
            uris.add(str(action['/URI']))
assert {item['reference']['url'] for item in ideas} <= uris
with pdfplumber.open(pdf) as document:
    char_count = 0
    for page in document.pages:
        assert '\ufffd' not in page.extract_text()
        for char in page.chars:
            assert 0 <= char['x0'] <= char['x1'] <= page.width
            assert 0 <= char['top'] <= char['bottom'] <= page.height
            char_count += 1
archive = folder.with_suffix('.zip')
with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as package:
    package.write(pdf, pdf.name)
    for file in sorted(folder.iterdir()):
        if file.is_file():
            package.write(file, 'Begleitdaten/' + file.name)
summary = {'passed': True, 'ideas': len(ideas), 'source_winter_posts': len(source), 'pdf_pages': len(reader.pages), 'validated_source_links': len(uris), 'pdf_characters_in_page_bounds': char_count, 'zip': str(archive), 'zip_bytes': archive.stat().st_size}
(folder / 'pruefung.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(summary, ensure_ascii=False, indent=2))
