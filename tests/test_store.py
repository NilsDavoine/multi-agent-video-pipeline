import pytest

from vidpipe.contracts import Clip
from vidpipe.store import StageStore, digest


def test_a_failed_stage_resumes_without_redoing_earlier_ones(tmp_path):
    calls = {"a": 0, "b": 0}

    def a():
        calls["a"] += 1
        return Clip(path="a")

    def b(fail):
        calls["b"] += 1
        if fail:
            raise RuntimeError("render crashed")
        return Clip(path="b")

    s1 = StageStore(tmp_path)
    s1.run("design/s01", Clip, "h1", a)
    with pytest.raises(RuntimeError):
        s1.run("render/s01", Clip, "h2", lambda: b(True))

    s2 = StageStore(tmp_path)
    s2.run("design/s01", Clip, "h1", a)
    s2.run("render/s01", Clip, "h2", lambda: b(False))
    assert calls == {"a": 1, "b": 2}
    assert [e["status"] for e in s2.events] == ["reused", "ran"]


def test_changed_inputs_or_missing_files_rerun_the_stage(tmp_path):
    n = {"k": 0}

    def make():
        n["k"] += 1
        return Clip(path=str(tmp_path / "out.mp4"))

    StageStore(tmp_path).run("render/s01", Clip, "h", make, files=lambda c: [c.path])
    assert n["k"] == 1  # the file was never created, so the record cannot be trusted
    StageStore(tmp_path).run("render/s01", Clip, "h", make, files=lambda c: [c.path])
    assert n["k"] == 2
    (tmp_path / "out.mp4").write_bytes(b"x")
    StageStore(tmp_path).run("render/s01", Clip, "h", make, files=lambda c: [c.path])
    assert n["k"] == 2
    StageStore(tmp_path).run("render/s01", Clip, "other inputs", make, files=lambda c: [c.path])
    assert n["k"] == 3


def test_forced_stage_reruns(tmp_path):
    n = {"k": 0}

    def make():
        n["k"] += 1
        return Clip(path="x")

    StageStore(tmp_path).run("design/s01", Clip, "h", make)
    StageStore(tmp_path, force={"design"}).run("design/s01", Clip, "h", make)
    assert n["k"] == 2


def test_digest_follows_file_contents_inside_lists(tmp_path):
    """Regression: a list of clip paths was hashed by name, so a re-rendered clip
    did not invalidate the assembly and a stale video was exported."""
    clip = tmp_path / "s01.mp4"
    clip.write_bytes(b"old render")
    before = digest([clip], {"clips": [clip]})
    clip.write_bytes(b"new render")
    assert digest([clip], {"clips": [clip]}) != before
