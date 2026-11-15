"""The coverage reader uses offsets from the exact bytes served to Chrome."""

import pytest

from conftest import STATIC, Coverage


def test_cdp_utf16_offsets_after_an_emoji_map_to_exact_characters(tmp_path, monkeypatch):
    import conftest

    monkeypatch.setattr(conftest, "STATIC", tmp_path)
    for name in conftest.COVERED_SCRIPTS:
        (tmp_path / name).write_text("// synthetic", encoding="utf-8")
    source = 'const marker="😀";\r\nif(flag){miss();} done();\n'
    (tmp_path / "app.js").write_bytes(source.encode("utf-8"))
    start = source.index("miss()")
    units = lambda text: len(text.encode("utf-16-le")) // 2
    coverage = Coverage()
    coverage.add(
        {
            "result": [
                {
                    "url": "http://localhost/static/app.js",
                    "functions": [
                        {
                            "ranges": [
                                {"startOffset": 0, "endOffset": units(source), "count": 1},
                                {
                                    "startOffset": units(source[:start]),
                                    "endOffset": units(source[: start + 6]),
                                    "count": 0,
                                },
                            ]
                        }
                    ],
                }
            ]
        }
    )
    assert coverage.counts["app.js"][start : start + 6] == [0] * 6
    assert coverage.uncovered()["app.js"] == [2]


@pytest.mark.parametrize("suffix", ["", "?v=synthetic"])
def test_cdp_offsets_preserve_windows_line_endings(suffix):
    source = (STATIC / "app.js").read_bytes().decode("utf-8")
    start = source.index("polling.delete(url)")
    expected_line = source.count("\n", 0, start) + 1
    units = lambda text: len(text.encode("utf-16-le")) // 2
    coverage = Coverage()
    coverage.add(
        {
            "result": [
                {
                    "url": "http://localhost/static/app.js" + suffix,
                    "functions": [
                        {
                            "ranges": [
                                {"startOffset": 0, "endOffset": units(source), "count": 1},
                                {
                                    "startOffset": units(source[:start]),
                                    "endOffset": units(source[: start + 4]),
                                    "count": 0,
                                },
                            ]
                        }
                    ],
                }
            ]
        }
    )
    assert coverage.uncovered()["app.js"] == [expected_line]
