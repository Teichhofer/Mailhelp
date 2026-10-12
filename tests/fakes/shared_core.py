"""Shared synthetic fixtures and doubles; no test-module dependencies."""
from __future__ import annotations

from pathlib import Path

from mailhelp.config import (
    PromptConfig,
    PromptStep,
)
from mailhelp.models import (
    Proposal,
)


def prompt_config(model="model"):
    return PromptConfig(defaults={"model": model, "parameters": {"temperature": .2}}, prompts={x: PromptStep(system_prompt=x, parameters={"max_tokens": 200}) for x in ("relevance", "summary", "action_router", "task_extraction", "event_extraction", "mail_question_resolution", "telegram_answer_interpretation", "telegram_answer_clarification", "proposal_revision", "learning_classification", "learning_abstraction", "calendar_duplicate")})

def proposal(**kw):
    base = dict(id="p1", version=1, kind="task", responsibility="user", certainty="certain", classification="new", title="Tun", evidence="Mail sagt es", source_mail_id="a"*24, target="inbox")
    if "status" not in kw and (kw.get("open_questions") or kw.get("responsibility") not in {None, "user"}
                               or kw.get("certainty") not in {None, "certain"}
                               or kw.get("classification") not in {None, "new"}):
        base["status"] = "needs_clarification"
    base.update(kw)
    return Proposal.model_validate(base)

def shipped_configuration(tmp_path):
    """The shipped example files in *tmp_path*; returns a complete synthetic environment."""
    for name in ("config.yaml", "prompts.yaml", "topics.yaml", "irrelevant_topics.yaml"):
        source = Path("config.example.yaml" if name == "config.yaml" else name)
        (tmp_path / name).write_text(source.read_text(encoding="utf8"), encoding="utf8")
    env = {x: "secret" for x in ["IMAP_USERNAME", "IMAP_PASSWORD", "OPENROUTER_API_KEY", "TELEGRAM_BOT_TOKEN", "TODOIST_TOKEN", "TODOIST_CLIENT_ID", "TODOIST_CLIENT_SECRET", "GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET", "GOOGLE_OAUTH_REFRESH_TOKEN"]}
    return env

class FakeImap:
    def __init__(self, *args, **kwargs):
        self.mode="ok"
        self.logged=False
    def login(self, *args): self.logged=True
    def select(self, folder, readonly): return (("NO", []) if folder == "bad" else ("OK", []))
    def response(self, key): return ((None, []) if self.mode == "validity" else ("UIDVALIDITY", [b"7"]))
    def uid(self, action, *args):
        if self.mode == "search": return "NO", []
        if action == "search": return "OK", [b"4"]
        if self.mode == "fetch": return "NO", []
        return "OK", [(b'4 (INTERNALDATE "17-Sep-2026 10:11:12 +0200")', b"raw")]
    def logout(self): self.logged=False
