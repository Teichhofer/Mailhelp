"""8.7.6 bugfix: Enter in a field of the learning form shows the estimate instead of loading folders.

Browsers submit a form on Enter through its first submit button in document order. Until 8.7.5
that was "Ordner laden" (``prepare=1``), so pressing Enter in the count or limit field only
reloaded the folders.
"""
from __future__ import annotations

import re
from types import SimpleNamespace as NS

import pytest

from mailhelp.web.learning_setup import setup_form


def worker():
    box = NS(id=1, label="Privat", folders=["INBOX"])
    return NS(app=NS(settings=NS(imap=NS(enabled_mailboxes=lambda: [box])),
                     analyzer=NS(prompts=NS(resolved_routes=lambda stage: ([NS(model="m")], None)))),
              jobs=NS(store=NS(load=lambda name, default: default)))


@pytest.mark.parametrize("customer", [False, True])
def test_the_default_button_of_the_learning_form_shows_the_estimate(customer):
    body, _ = setup_form(worker(), "", customer=customer)
    form = re.search(r'<form method="get" action="/lernen/postfach"[^>]*>(.*?)</form>', body, re.S).group(1)
    first = re.search(r"<button\b[^>]*>", form).group(0)
    assert 'name="prepare"' not in first  # Enter must not mean "Ordner laden"
    assert first == "<button hidden>"  # not a second visible control
    assert form.count('name="prepare"') == 1
