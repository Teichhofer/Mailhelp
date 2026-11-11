"""Synthetic help answers shared by browser scenarios; no provider calls."""
from types import SimpleNamespace

from mailhelp.config import HelpChatSettings
from mailhelp.helpdocs import HelpAnswer, load
from mailhelp.helpdocs.chat import HelpChat


class Analyzer:
    prompts = SimpleNamespace(prompts={"settings_help": object()})

    def settings_help(self, question, sources, history, settings, *, before_call=lambda: None):
        before_call()
        return "synthetic", HelpAnswer(answer="Das Intervall steuert den Mailabruf.",
                                       source_ids=[sources[0].id], setting_ids=["setting:poll_interval_seconds"])


def chat_service(mailhelp):
    service = HelpChat(mailhelp.store, HelpChatSettings, load, Analyzer, mailhelp.auth.active)
    mailhelp.site.archive.help.chat = service
    return service
