"""7.1 (D3): the packaged demo dataset is verified and copied atomically into one area per visitor."""
from __future__ import annotations

import json
import shutil

import pytest

from mailhelp.persistence.storage import JsonStore
from mailhelp.review.views import ReviewViews
from mailhelp.runtime import demo_dataset
from mailhelp.runtime.demo_dataset import DemoDatasetError, install, packaged, verify
from mailhelp.runtime.demo_visitors import DemoLimitReached, DemoVisitors


@pytest.fixture
def dataset(tmp_path):
    copy = tmp_path / "dataset"
    shutil.copytree(packaged(), copy)
    return copy


def _manifest(path):
    return json.loads((path / "manifest.json").read_text(encoding="utf-8"))


def _write(path, manifest):
    (path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_the_packaged_dataset_holds_thirty_mails_and_matches_every_digest():
    manifest = verify(packaged())
    assert manifest.dataset == "standard-v1" and len(manifest.mails) == 30 and manifest.files


@pytest.mark.parametrize("name", ["state/unlisted.json", "mails/unlisted.eml"])
def test_dataset_refuses_files_outside_the_manifest(dataset, name):
    (dataset / name).write_text("{}", encoding="utf-8")
    with pytest.raises(DemoDatasetError):
        verify(dataset)


def test_manifest_refuses_windows_traversal_and_case_collisions(dataset):
    for name in ["..\\outside.json", "C:/outside.json", "./mail.json", "MAIL.json"]:
        manifest = _manifest(dataset)
        manifest["files"] = {"mail.json": "0" * 64, name: "0" * 64}
        _write(dataset, manifest)
        with pytest.raises(DemoDatasetError, match="nicht lesbar"):
            verify(dataset)


def test_failed_reset_keeps_the_existing_visitor_area(visitors, monkeypatch):
    from mailhelp.runtime import demo_visitors
    old = visitors.start("s1", "k1")
    def fail(*args):
        raise OSError("copy failed")
    monkeypatch.setattr(demo_visitors, "install", fail)
    with pytest.raises(OSError, match="copy failed"):
        visitors.reset("s1", "k2")
    assert visitors.area("s1") == old and old.is_dir()


def test_reset_retries_return_the_same_generation(visitors):
    visitors.start("s1", "k1")
    new = visitors.reset("s1", "k2")
    assert visitors.reset("s1", "k2") == new


def test_late_snapshot_damage_keeps_old_generation_and_is_cleaned_after_restart(visitors, monkeypatch):
    from mailhelp.runtime import demo_visitors
    old = visitors.start("s1", "start")
    original = demo_visitors.install
    def install_then_damage(source, target):
        manifest = original(source, target)
        (source / "answers.json").write_text('[{}]', encoding="utf-8")
        return manifest
    monkeypatch.setattr(demo_visitors, "install", install_then_damage)
    with pytest.raises(DemoDatasetError, match="während der Installation"):
        visitors.reset("s1", "reset", generation=1)
    assert visitors.area("s1") == old and visitors.entry("s1").generation == 1
    assert visitors.cleanup({"s1"}) == 1
    assert list(visitors.root.iterdir()) == [old]


def test_stale_migration_read_preserves_the_already_migrated_index(visitors, monkeypatch):
    from mailhelp.runtime.demo_visitors import VisitorState
    visitors.start("s1", "start")
    real = visitors.store.load_model
    def stale_read(name, *args):
        result = real(name, *args)
        return result.model_copy(update={"schema_version": 1}) if name == "demo-visitors" else result
    monkeypatch.setattr(visitors.store, "load_model", stale_read)
    assert visitors.entry("s1").dataset_revision != "unknown"
    assert visitors.store.load("demo-visitors-v1-backup") is None


def test_save_failure_keeps_the_prior_activation_and_orphan_cleanup(visitors, monkeypatch):
    old = visitors.start("s1", "start")
    original = visitors.store.save
    def fail_activation(name, payload):
        if name == "demo-visitors":
            raise OSError("activation interrupted")
        return original(name, payload)
    with monkeypatch.context() as local:
        local.setattr(visitors.store, "save", fail_activation)
        with pytest.raises(OSError, match="activation interrupted"):
            visitors.reset("s1", "reset", generation=1)
    assert visitors.area("s1") == old
    assert visitors.cleanup({"s1"}) == 1 and old.is_dir()


def test_migration_preserves_legacy_areas_and_saves_the_original_index(visitors):
    import hashlib
    old_area = visitors.root / ("a" * 32)
    install(visitors.dataset, old_area)
    owner = hashlib.sha256(b"legacy").hexdigest()
    legacy = {"schema_version": 1, "visitors": {owner: {"area": old_area.name, "created_at": 42.0}},
              "starts": {"legacy-key": owner}}
    visitors.store.save("demo-visitors", legacy)
    assert visitors.area("legacy") == old_area
    assert visitors.entry("legacy").dataset_locale == "de"
    assert visitors.entry("legacy").dataset_revision == "unknown"
    assert visitors.entry("legacy").created_at == 42.0
    assert visitors.store.load("demo-visitors-v1-backup") == legacy
    assert visitors.store.load("demo-visitors")["schema_version"] == 2


def test_orders_bind_operation_locale_owner_and_generation(visitors):
    from mailhelp.i18n import Locale
    first = visitors.start("s1", "start-en", Locale.EN)
    entry = visitors.entry("s1")
    assert entry.dataset_id == "standard-en-v1" and entry.generation == 1
    assert (first / ".demo" / "answers.json").is_file()
    with pytest.raises(ValueError, match="anderen Inhalt"):
        visitors.start("s1", "start-en", Locale.DE)
    with pytest.raises(ValueError, match="anderen Inhalt"):
        visitors.reset("s1", "start-en", Locale.EN)
    new = visitors.reset("s1", "reset-de")
    assert new != first and visitors.entry("s1").generation == 2
    with pytest.raises(ValueError, match="älteren Demo-Generation"):
        visitors.start("s1", "start-en", Locale.EN)


@pytest.mark.parametrize("change", [
    lambda m: m.update(dataset="anderer"),
    lambda m: m.update(schema_version=2),
    lambda m: m.update(reference_time="2026-11-16T09:00:00"),
    lambda m: m.update(timezone="UTC"),
    lambda m: m.update(mails=m["mails"][:29]),
    lambda m: m["mails"].__setitem__(1, {**m["mails"][1], "message_id": m["mails"][0]["message_id"]}),
    lambda m: m["mails"].__setitem__(1, {**m["mails"][1], "name": m["mails"][0]["name"]}),
    lambda m: m["files"].update({"../draussen.json": "0" * 64}),
    lambda m: m["files"].update({"/absolut.json": "0" * 64}),
    lambda m: m["files"].update({"kein-json.txt": "0" * 64}),
    lambda m: m["files"].update({"ok.json": "kein-hash"}),
])
def test_a_wrong_manifest_is_refused(dataset, change):
    manifest = _manifest(dataset)
    change(manifest)
    _write(dataset, manifest)
    with pytest.raises(DemoDatasetError, match="nicht lesbar oder unvollständig"):
        verify(dataset)


def test_an_unreadable_manifest_and_damaged_or_missing_files_are_refused(dataset):
    first = next(iter(_manifest(dataset)["files"]))
    (dataset / "state" / first).write_text("{}", encoding="utf-8")
    with pytest.raises(DemoDatasetError, match=f"beschädigt: state/{first}"):
        verify(dataset)
    (dataset / "state" / first).unlink()
    with pytest.raises(DemoDatasetError, match="beschädigt"):
        verify(dataset)
    (dataset / "manifest.json").write_text("{kaputt", encoding="utf-8")
    with pytest.raises(DemoDatasetError, match="nicht lesbar"):
        verify(dataset)


@pytest.mark.parametrize("root_link,junction", [(False, False), (True, False), (False, True), (True, True)])
def test_links_and_windows_junctions_cannot_escape_the_corpus(dataset, monkeypatch, root_link, junction):
    from pathlib import Path
    method = "is_junction" if junction else "is_symlink"
    real = getattr(Path, method)
    target = dataset if root_link else dataset / "answers.json"
    monkeypatch.setattr(Path, method, lambda path: path == target or real(path))
    with pytest.raises(DemoDatasetError, match="Verknüpfung"):
        verify(dataset)


def test_install_copies_the_states_once_and_leaves_nothing_after_a_failure(dataset, tmp_path, monkeypatch):
    target = tmp_path / "visitors" / "a"
    install(dataset, target)
    assert sorted(path.name for path in target.iterdir()) == sorted(_manifest(dataset)["files"])
    with pytest.raises(DemoDatasetError, match="bereits belegt"):
        install(dataset, target)
    real_copy = shutil.copytree

    def damaging_copy(source, destination):
        real_copy(source, destination)
        next(destination.iterdir()).write_text("{}", encoding="utf-8")
    monkeypatch.setattr(demo_dataset.shutil, "copytree", damaging_copy)
    with pytest.raises(DemoDatasetError, match="Kopie des Beispielbestands ist beschädigt"):
        install(dataset, tmp_path / "visitors" / "b")
    assert sorted(path.name for path in (tmp_path / "visitors").iterdir()) == ["a"]


def test_a_visitor_area_is_an_ordinary_store_with_the_prepared_proposals(dataset, tmp_path):
    target = tmp_path / "area"
    install(dataset, target)
    with JsonStore(target) as store:
        overview = ReviewViews(store, "Europe/Berlin", test_mode=True).overview()
    assert len(overview.open) >= 10 and overview.damaged == 0


@pytest.fixture
def visitors(tmp_path, dataset):
    store = JsonStore(tmp_path / "core").__enter__()
    yield DemoVisitors(store, tmp_path / "visitors", dataset, max_visitors=2, clock=lambda: 1000.0)
    store.__exit__(None, None, None)


def test_a_start_is_idempotent_and_bound_to_its_session(visitors):
    assert visitors.area("s1") is None
    first = visitors.start("s1", "key-1")
    assert visitors.start("s1", "key-1") == first == visitors.area("s1")
    assert visitors.start("s1", "key-2") == first  # a second click on a new page keeps the same demo
    with pytest.raises(ValueError, match="anderen Sitzung"):
        visitors.start("s2", "key-1")
    assert "s1" not in (visitors.store.directory / "demo-visitors.json").read_text(encoding="utf-8")


def test_the_limit_never_removes_another_visitor(visitors):
    visitors.start("s1", "k1")
    visitors.start("s2", "k2")
    with pytest.raises(DemoLimitReached, match="alle Demo-Plätze"):
        visitors.start("s3", "k3")
    assert visitors.area("s1") and visitors.area("s2") and visitors.area("s3") is None


def test_a_deleted_area_is_recreated_and_reset_touches_only_the_own_area(visitors):
    first = visitors.start("s1", "k1")
    other = visitors.start("s2", "k2")
    shutil.rmtree(first)
    assert visitors.area("s1") is None
    again = visitors.start("s1", "k1")
    assert again != first and again.is_dir()
    fresh = visitors.reset("s1", "k3")
    assert fresh != again and not again.exists() and fresh.is_dir() and other.is_dir()
    visitors.cleanup({"s1"})
    assert visitors.reset("s4", "k4").is_dir()  # without an area a reset is a first start


def test_cleanup_removes_ended_sessions_and_orphaned_copies(visitors, tmp_path):
    assert visitors.cleanup(set()) == 0  # no area yet
    kept = visitors.start("s1", "k1")
    ended = visitors.start("s2", "k2")
    (tmp_path / "visitors" / ".halb.neu").mkdir()
    assert visitors.cleanup({"s1"}) == 2
    assert kept.is_dir() and not ended.exists() and visitors.area("s2") is None
    assert visitors.start("s3", "k2").is_dir()  # the start key of the ended session is free again
