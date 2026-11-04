import json

from ndpa.evidence import chain


def make(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "one.txt").write_text("first")
    (tmp_path / "two.json").write_text('{"x": 1}')
    return tmp_path


def test_a_fresh_manifest_verifies_and_has_a_final_hash(tmp_path):
    folder = make(tmp_path)
    manifest = chain.build_manifest(folder)
    problems, final = chain.verify(folder)
    assert problems == [] and final == manifest["final"] and len(final) == 64
    assert [e["path"] for e in manifest["entries"]] == ["a/one.txt", "two.json"]


def test_the_same_files_give_the_same_final_hash(tmp_path):
    a, b = make(tmp_path / "a" if (tmp_path / "a").mkdir() or True else tmp_path), None
    other = tmp_path / "copy"
    other.mkdir()
    (other / "a").mkdir()
    (other / "a" / "one.txt").write_text("first")
    (other / "two.json").write_text('{"x": 1}')
    assert chain.build_manifest(a)["final"] == chain.build_manifest(other)["final"]


def test_changing_a_file_is_detected(tmp_path):
    folder = make(tmp_path)
    chain.build_manifest(folder)
    (folder / "a" / "one.txt").write_text("changed")
    assert "file changed: a/one.txt" in chain.verify(folder)[0]


def test_removing_and_adding_files_are_detected(tmp_path):
    folder = make(tmp_path)
    chain.build_manifest(folder)
    (folder / "two.json").unlink()
    (folder / "extra.txt").write_text("new")
    problems = chain.verify(folder)[0]
    assert "missing file: two.json" in problems and "file not in the manifest: extra.txt" in problems


def test_editing_the_manifest_breaks_the_chain(tmp_path):
    folder = make(tmp_path)
    chain.build_manifest(folder)
    manifest = json.loads((folder / "manifest.json").read_text())
    manifest["entries"][0]["sha256"] = "0" * 64
    (folder / "manifest.json").write_text(json.dumps(manifest))
    problems = chain.verify(folder)[0]
    assert any("file changed" in p for p in problems) and any("chain broken" in p for p in problems)


def test_a_rewritten_manifest_is_caught_by_the_recorded_final_hash(tmp_path):
    folder = make(tmp_path)
    recorded = chain.build_manifest(folder)["final"]
    (folder / "a" / "one.txt").write_text("forged")
    chain.build_manifest(folder)  # the forger rebuilds the manifest, so it is self-consistent again
    assert chain.verify(folder)[0] == []
    assert chain.verify(folder, expect=recorded)[0] == ["the final hash is not the expected one"]


def test_missing_manifest_and_the_command_line(tmp_path, capsys):
    assert chain.verify(tmp_path)[0] == ["manifest.json is missing"]
    folder = make(tmp_path)
    final = chain.build_manifest(folder)["final"]
    assert chain.main([str(folder), "--expect", final]) == 0
    assert "OK" in capsys.readouterr().out
    (folder / "two.json").write_text("{}")
    assert chain.main([str(folder)]) == 1
