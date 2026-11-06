"""Both safe YAML implementations reject executable tags and preserve configuration types."""
from datetime import date

import pytest
import yaml

from mailhelp.config.loader import read_yaml


@pytest.mark.parametrize("compiled", [True, False])
def test_safe_loader_preserves_configuration_types_and_rejects_executable_tags(tmp_path, monkeypatch, compiled):
    if not compiled:
        monkeypatch.delattr(yaml, "CSafeLoader", raising=False)
    path = tmp_path / "config.yaml"
    path.write_text("name: Grüße\nenabled: true\ncount: 3\nempty: null\nday: 2026-11-06\n", encoding="utf-8")
    assert read_yaml(path) == {"name": "Grüße", "enabled": True, "count": 3, "empty": None,
                               "day": date(2026, 11, 6)}
    path.write_text("value: !!python/object/apply:os.getcwd []", encoding="utf-8")
    with pytest.raises(yaml.constructor.ConstructorError):
        read_yaml(path)
    path.write_text("[one, two]", encoding="utf-8")
    with pytest.raises(ValueError, match="Wurzel muss ein Objekt sein"):
        read_yaml(path)
    path.write_text("value: [", encoding="utf-8")
    with pytest.raises(yaml.YAMLError):
        read_yaml(path)
