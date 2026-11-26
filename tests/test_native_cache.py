import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "cache_adapter", ROOT / "examples/abseil/native_cache.py"
)
assert SPEC and SPEC.loader
cache = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cache)


def populated(tmp_path):
    path = tmp_path / "cache"
    path.mkdir()
    (path / "cas").mkdir()
    (path / "cas/a").write_bytes(b"build output")
    return path


def test_fingerprint_is_location_independent_and_content_bound(tmp_path):
    first = populated(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    second = populated(other)
    assert cache.fingerprint(first) == cache.fingerprint(second)
    (second / "cas/a").write_bytes(b"changed byte")
    assert (
        cache.fingerprint(first)["tree_digest"]
        != cache.fingerprint(second)["tree_digest"]
    )


@pytest.mark.parametrize("kind", ["file_link", "directory_link", "hard_link", "fifo"])
def test_cache_rejects_links_and_special_files(tmp_path, kind):
    path = populated(tmp_path)
    extra = path / "untrusted"
    if kind == "file_link":
        extra.symlink_to(path / "cas/a")
    elif kind == "directory_link":
        extra.symlink_to(tmp_path, target_is_directory=True)
    elif kind == "hard_link":
        os.link(path / "cas/a", extra)
    else:
        os.mkfifo(extra)
    with pytest.raises(ValueError):
        cache.fingerprint(path)


def test_publication_is_bounded_before_upload(tmp_path, monkeypatch):
    path = populated(tmp_path)
    monkeypatch.setattr(cache, "MAX_BYTES", 4)
    with pytest.raises(ValueError, match="upload cap"):
        cache.fingerprint(path)
    monkeypatch.setattr(cache, "MAX_BYTES", 100)
    monkeypatch.setattr(cache, "MAX_ENTRIES", 1)
    with pytest.raises(ValueError, match="entry limit"):
        cache.fingerprint(path)


def test_empty_seed_and_root_symlink_are_rejected(tmp_path):
    path = tmp_path / "empty"
    path.mkdir()
    with pytest.raises(ValueError, match="empty"):
        cache.fingerprint(path)
    link = tmp_path / "alias"
    link.symlink_to(path, target_is_directory=True)
    with pytest.raises(ValueError, match="canonical"):
        cache.fingerprint(link)


def test_cache_depth_is_bounded(tmp_path):
    path = tmp_path / "cache"
    path.mkdir()
    child = path
    for _ in range(65):
        child = child / "d"
        child.mkdir()
    with pytest.raises(ValueError, match="nesting"):
        cache.fingerprint(path)


def test_restore_checks_separately_authenticated_manifest(tmp_path, monkeypatch):
    path = populated(tmp_path)
    expected = tmp_path / "expected.json"
    expected.write_text(json.dumps(cache.fingerprint(path)))
    output = tmp_path / "verified.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "cache",
            "--directory",
            str(path),
            "--output",
            str(output),
            "--expected",
            str(expected),
        ],
    )
    assert cache.main() == 0
    output.unlink()
    (path / "cas/a").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="approved seed"):
        cache.main()
    assert not output.exists()


@pytest.mark.parametrize("kind", ["source", "capture", "ancestor", "shell"])
def test_mount_cannot_expose_checkout_output_or_shell_syntax(tmp_path, kind):
    repo, output = tmp_path / "repo", tmp_path / "evidence"
    repo.mkdir()
    output.mkdir()
    path = {
        "source": repo,
        "capture": output,
        "ancestor": tmp_path,
        "shell": tmp_path / "cache;touch",
    }[kind]
    path.mkdir(exist_ok=True)
    with pytest.raises(ValueError):
        cache.cache_arguments(path, repo, output)


def test_cache_profile_and_directory_must_agree(tmp_path):
    cold = json.loads((ROOT / "examples/abseil/capture-profile.json").read_bytes())
    warm = json.loads((ROOT / "examples/abseil/cache-profile.json").read_bytes())
    cache.validate_profile_options(cold["options_digest"], None)
    cache.validate_profile_options(warm["options_digest"], tmp_path)
    for options, path in [
        (cold["options_digest"], tmp_path),
        (warm["options_digest"], None),
    ]:
        with pytest.raises(ValueError):
            cache.validate_profile_options(options, path)
    assert cold["environment_digest"] != warm["environment_digest"]


@pytest.mark.parametrize("module_name", ["collection_driver", "execution_driver"])
def test_reviewed_configs_include_cache_and_reject_profile_mismatch(
    tmp_path, monkeypatch, module_name
):
    monkeypatch.syspath_prepend(str(ROOT / "examples/abseil"))
    driver = __import__(module_name)
    output = tmp_path / "config.json"
    driver.configure(
        ROOT / "examples/abseil/cache-profile.json", output, tmp_path / "cache"
    )
    config = json.loads(output.read_bytes())
    for stage in (
        ("native", "query")
        if module_name == "collection_driver"
        else ("full", "subset")
    ):
        assert config[stage]["argv"][-2:] == ["--native-cache", str(tmp_path / "cache")]
    if module_name == "execution_driver":
        assert config["subset_options_digest"] == driver.CACHED_SUBSET_OPTIONS
    with pytest.raises(ValueError, match="must agree"):
        driver.configure(
            ROOT / "examples/abseil/capture-profile.json", output, tmp_path / "cache"
        )


def test_duplicate_receipt_fields_are_rejected():
    with pytest.raises(ValueError, match="duplicate"):
        json.loads('{"files":1,"files":2}', object_pairs_hook=cache.unique_object)
