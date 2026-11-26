"""8.7.8 (AP4c): the customer's part of the help – no money, servers, credentials, prompts or host commands."""
from __future__ import annotations

import re

import pytest

from mailhelp.helpdocs import load
from mailhelp.helpdocs.roles import CUSTOMER_SECTIONS
from mailhelp.i18n import Locale

# Words of the operator's world; a listed section must not contain any of them, in either language.
OPERATOR_WORDS = re.compile(
    r"USD|EUR|€|\bCent\b|[Kk]osten|kostenpflichtig|\b[Cc]osts?\b|\bpaid\b|[Pp]reis|\bprices?\b|\.env\b|config\.yaml|"
    r"prompts\.yaml|OPENROUTER|OpenRouter|[Dd]ocker|systemd|nginx|Terminal|terminal|\s--[a-z]|/diagnose|/einrichtung\b|"
    r"/status\b|/auswertung|/abgleich|→ Zugangsdaten|→ Credentials|kostet|OAuth-Playground")


@pytest.mark.parametrize("locale", [Locale.DE, Locale.EN])
def test_every_customer_section_exists_and_speaks_without_operator_words(locale):
    base = load(locale=locale)
    ids = {section.id for section in base.sections}
    assert CUSTOMER_SECTIONS <= ids
    found = [(section.id, match.group(0)) for section in base.sections if section.id in CUSTOMER_SECTIONS
             for match in [OPERATOR_WORDS.search(section.title + "\n" + section.text)] if match]
    assert found == []
