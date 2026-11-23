"""8.5: submit the settings section forms the way a browser does (all values of the section)."""
import re
from html import unescape

from mailhelp.web.settings_pages import AREAS, SETTING_PREFIX, _names


def area_of(name: str) -> str:
    """The area whose page shows *name*."""
    return next(key for key, _title, _text, groups in AREAS if any(name in _names(group) for group in groups))


def section_fields(html: str, name: str) -> dict[str, str]:
    """Every value the section form holding *name* would send, as a browser submits it."""
    marker = f'name="{SETTING_PREFIX}{name}"'
    block = next(block for block in re.findall(r'<form method="post" action="/einstellungen/speichern"[^>]*>(.*?)</form>',
                                               html, re.S) if marker in block)
    fields = {key: unescape(value) for key, value in re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)">',
                                                                 block)}
    for key, value in re.findall(r'<input type="(?:number|text)"[^>]* name="([^"]+)" value="([^"]*)"', block):
        fields[unescape(key)] = unescape(value)
    for key, value in re.findall(r'<textarea name="([^"]+)"[^>]*>(.*?)</textarea>', block, re.S):
        fields[unescape(key)] = unescape(value)
    for key, options in re.findall(r'<select name="([^"]+)"[^>]*>(.*?)</select>', block, re.S):
        chosen = re.search(r'<option value="([^"]*)" selected', options) or re.search(r'<option value="([^"]*)"',
                                                                                      options)
        fields[unescape(key)] = unescape(chosen.group(1)) if chosen else ""
    return fields


def single_setting_form(web, name: str, area: str = "") -> dict[str, str]:
    """The fields of the single-value form (``name``/``value``) the search results offer for *name*."""
    page = web.browser.request("GET", f"/einstellungen?bereich={area or area_of(name)}").body.decode()
    fields = section_fields(page, name)
    return {"csrf": fields["csrf"], "key": fields["key"], "expected_hash": fields["expected_hash"], "name": name}


def change_setting(web, name: str, value: str, *, confirm: bool = True, area: str = "", **extra: str):
    """Change one value through its section form; without *confirm* the review page answers."""
    page = web.browser.request("GET", f"/einstellungen?bereich={area or area_of(name)}").body.decode()
    form = {**section_fields(page, name), SETTING_PREFIX + name: value, **extra}
    if confirm:
        review = web.browser.request("POST", "/einstellungen/speichern", form)
        if review.status != 200 or 'name="confirm"' not in review.body.decode():
            return review
        form = review_fields(review.body.decode())
    return web.browser.request("POST", "/einstellungen/speichern", form)


def review_fields(html: str) -> dict[str, str]:
    """The hidden fields of the confirmation form on the review page."""
    block = re.search(r'<form method="post" action="/einstellungen/speichern"[^>]*>(.*?)</form>', html, re.S).group(1)
    return {key: unescape(value) for key, value in re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)">',
                                                              block)}
