"""The coverage reader uses offsets from the exact bytes served to Chrome."""
from conftest import STATIC, Coverage


def test_cdp_offsets_preserve_windows_line_endings():
    source = (STATIC / "app.js").read_bytes().decode("utf-8")
    start = source.index("|| 5000") + 3
    expected_line = source.count("\n", 0, start) + 1
    coverage = Coverage()
    coverage.add({"result": [{"url": "http://localhost/static/app.js", "functions": [{"ranges": [
        {"startOffset": 0, "endOffset": len(source), "count": 1},
        {"startOffset": start, "endOffset": start + 4, "count": 0}]}]}]})
    assert coverage.uncovered()["app.js"] == [expected_line]
