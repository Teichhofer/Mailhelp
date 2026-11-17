"""7.5.4: the review views are built in the reader's language, also from the cached overview."""
from mailhelp.i18n import Locale, use_locale
from mailhelp.persistence.storage import JsonStore
from mailhelp.review.views import ReviewViews
from tests.fakes.reconciliation_fakes import Events, process


def test_regression_the_cached_overview_is_not_shared_between_languages(tmp_path):
    """Before 7.5.4 an English reader left English cards in the cache for the next German one."""
    store = JsonStore(tmp_path)
    process(store, Events())
    views = ReviewViews(store, "Europe/Berlin")
    with use_locale(Locale.EN):
        english = views.overview().open[0]
    german = views.overview().open[0]
    assert "Nov 20, 2030" in english.card.when and "20.11.2030" in german.card.when
    assert english.confirm_label == "Add to calendar" and german.confirm_label == "Im Kalender anlegen"
    assert english.state == "Pending confirmation" and german.state == "Wartet auf Bestätigung"
    with use_locale(Locale.EN):
        assert views.overview().open[0] == english
