"""5.9.5: the source mail of a proposal is collapsed from the server and names its content."""
from mailhelp.domain.prepared import PreparedAttachment
from mailhelp.review.views import MailView
from mailhelp.web.review_pages import detail_page, source_summary
from tests.scenarios.web_scenario import mail_id

TITLE = "Quellbeleg aus E-Mail / Anhang"


def mail(sender="Schule <info@schule.test>", previews=0, text="Text"):
    attachments = tuple(PreparedAttachment.model_validate(
        {"filename": f"scan{index}.png", "preview": {"index": index, "size_bytes": 10}} if index < previews
        else {"filename": "brief.pdf"}) for index in range(previews + 1))
    return MailView(mail_id(1), sender, "Elternabend", None, text, 0, False, attachments)


def test_the_summary_names_the_sender_and_the_images():
    assert source_summary(None) == TITLE
    assert source_summary(mail()) == f"{TITLE} (Mail von Schule)"
    assert source_summary(mail(previews=1)) == f"{TITLE} (Mail von Schule, 1 Bild)"
    assert source_summary(mail("info@schule.test", previews=2)) == f"{TITLE} (Mail von info@schule.test, 2 Bilder)"
    assert source_summary(mail("—", previews=2)) == f"{TITLE} (2 Bilder)"
    assert source_summary(mail("—")) == TITLE


def test_regression_the_sender_in_the_summary_is_escaped():
    """Mail headers are untrusted: a crafted display name must not become markup."""
    summary = source_summary(mail('"<img src=x onerror=alert(1)>" <x@example.test>'))
    assert "<img" not in summary and "&lt;img" in summary


def test_the_source_is_collapsed_and_marked_even_with_images(web):
    """Regression 5.9.5: image previews opened the source on small screens while a task from a text
    mail stayed closed even in the split view; the server now always renders it collapsed."""
    from mailhelp.review.views import ReviewViews
    view = ReviewViews(web.store, "Europe/Berlin").proposal(mail_id(1), "elternabend")
    for item in (mail(), mail(previews=2)):
        page = detail_page(view, mail=item)
        assert page.count("<details class=\"disclosure\" data-source-mail><summary>") == 1
        assert "data-source-mail open" not in page
