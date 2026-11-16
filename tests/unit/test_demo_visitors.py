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


@pytest.mark.parametrize("change", [
    lambda m: m.update(dataset="anderer"),
    lambda m: m.update(schema_version=2),
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
