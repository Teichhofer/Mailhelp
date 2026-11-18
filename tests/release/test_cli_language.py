"""7.8: explicit command-line language works before configuration or service construction."""
import sys

import pytest

from mailhelp import cli
from mailhelp.i18n import Locale, current, use_locale
from mailhelp.i18n.en import EN


@pytest.mark.parametrize("language, expected", [("en", "Validate configuration and exit"),
                                                ("de", "Konfiguration validieren und beenden")])
def test_help_selects_language_without_loading_configuration(monkeypatch, capsys, language, expected):
    def forbidden(*args, **kwargs):
        raise AssertionError("Help must not load configuration or build services")
    monkeypatch.setattr(cli, "load_all", forbidden)
    monkeypatch.setattr(cli, "build_application", forbidden)
    monkeypatch.setattr(sys, "argv", ["mailhelp", "--language", language, "--help"])
    with pytest.raises(SystemExit) as stopped:
        cli.main()
    assert stopped.value.code == 0 and expected in capsys.readouterr().out
    assert current() == Locale.DE


def test_early_option_errors_are_english_and_leave_the_locale_unchanged(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["mailhelp", "--language=en", "--profile", "1", "--check"])
    with pytest.raises(SystemExit) as stopped:
        cli.main()
    assert stopped.value.code == 2
    assert "--profile requires --google-auth or --microsoft-login" in capsys.readouterr().err
    assert current() == Locale.DE


def test_all_owned_parser_help_strings_have_a_translation():
    with use_locale(Locale.DE):
        parser = cli._parser()
    assert [a.help for a in parser._actions if a.help and a.dest != "help" and a.help not in EN] == []


def test_optional_parser_extensions_without_help_are_left_unchanged(monkeypatch):
    original = cli.LanguageParser
    class ExtendedParser(original):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.add_argument("--extension-without-help")
    monkeypatch.setattr(cli, "LanguageParser", ExtendedParser)
    with use_locale(Locale.EN):
        parser = cli._parser()
    assert next(a for a in parser._actions if a.dest == "extension_without_help").help is None
