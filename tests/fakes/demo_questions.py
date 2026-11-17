"""7.6: a copy of the demo dataset with exactly one open question and its prepared answer.

The shipped demo asks nothing any more (Planung 7.6), but the demo still replays prepared answers for
datasets that do. This copy turns the violin recital back into a question, records the answer the
real answer path would have produced and keeps the manifest checksums valid.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from mailhelp.runtime.demo_dataset import packaged

QUESTION = "Wann beginnt der Termin?"
ANSWER = "Um 16:00 Uhr, Dauer anderthalb Stunden."
TITLE = "Vorspielnachmittag der Geigenklasse"


def _write(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def asked_dataset(target: Path) -> Path:
    """Copy the packaged dataset to ``target`` and open one question on the recital."""
    shutil.copytree(packaged(), target)
    state = target / "state"
    mail = next(path for path in state.glob("mail-*.json") if TITLE in path.read_text(encoding="utf-8"))
    data = json.loads(mail.read_text(encoding="utf-8"))
    proposal = next(item for item in data["proposals"] if item["title"] == TITLE)
    mail_id, proposal_id = data["id"], proposal["id"]
    asked = {"status": "needs_clarification", "open_questions": [QUESTION]}
    proposal.update(asked)
    _write(mail, data)
    current = state / f"proposal-{mail_id}-{proposal_id}.json"
    answered = {**json.loads(current.read_text(encoding="utf-8")), "version": 2}
    for path in (current, state / f"proposal-{mail_id}-{proposal_id}-v1.json"):
        _write(path, {**json.loads(path.read_text(encoding="utf-8")), **asked})
    subject = [mail_id, proposal_id, 1]
    _write(target / "answers.json", [
        {"method": "interpret_telegram_answer", "proposal": subject, "arguments": [QUESTION, ANSWER],
         "result": {"usable": True, "normalized_answer": ANSWER, "reason": "Beginn und Dauer genannt"}},
        {"method": "revise_proposal", "proposal": subject, "arguments": [QUESTION, ANSWER], "result": answered}])
    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    for name in manifest["files"]:
        manifest["files"][name] = hashlib.sha256((state / name).read_bytes()).hexdigest()
    manifest["answers"] = hashlib.sha256((target / "answers.json").read_bytes()).hexdigest()
    _write(target / "manifest.json", manifest)
    return target
