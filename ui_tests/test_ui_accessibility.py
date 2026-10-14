"""axe-core really runs inside the page audit (Planung 2.1, T7)."""
from checks import axe_findings


def test_axe_reports_a_known_violation_and_accepts_a_clean_page(page):
    page.set_content('<html lang="de"><head><title>t</title></head><body><main>'
                     '<img src="x.png"></main></body></html>')
    assert any(finding.startswith("axe image-alt") for finding in axe_findings(page))
    page.set_content('<html lang="de"><head><title>t</title></head><body><main>'
                     '<img src="x.png" alt="Logo"></main></body></html>')
    assert axe_findings(page) == []
