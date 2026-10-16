import pytest

from transcript.converters.base import Converter, Edge
from transcript.engine import Context, Options, Reporter, Workspace, execute
from transcript.planner import Route
from transcript.tools import ConversionError


class Upper(Converter):
    name = "upper"

    def convert(self, src, dst, edge, ctx):
        (ctx.scratch() / "junk.tmp").write_text("intermediate")
        dst.write_text(src.read_text().upper())
        return dst


class Broken(Converter):
    name = "broken"

    def convert(self, src, dst, edge, ctx):
        dst.write_text("half written")
        raise ConversionError("boom")


def route(converter, src="txt", dst="md"):
    return Route((Edge(src, dst, converter),), 1.0)


def run(tmp_path, converter, overwrite=False):
    src = tmp_path / "note.txt"
    if not src.exists():
        src.write_text("hello")
    with Workspace(tmp_path / "ws") as workspace:
        ctx = Context(workspace, Options(), Reporter())
        result = execute(route(converter), src, tmp_path, ctx, overwrite=overwrite)
    return workspace, result


def test_workspace_is_removed_after_success(tmp_path):
    workspace, result = run(tmp_path, Upper())
    assert result == tmp_path / "note.md"
    assert result.read_text() == "HELLO"
    assert not workspace.exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["note.md", "note.txt", "ws"]


def test_workspace_is_removed_after_failure(tmp_path):
    with pytest.raises(ConversionError):
        run(tmp_path, Broken())
    assert list((tmp_path / "ws").iterdir()) == []
    assert not (tmp_path / "note.md").exists()


def test_workspace_is_removed_on_ctrl_c(tmp_path):
    class Interrupted(Converter):
        def convert(self, src, dst, edge, ctx):
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run(tmp_path, Interrupted())
    assert list((tmp_path / "ws").iterdir()) == []


def test_existing_files_are_never_replaced(tmp_path):
    (tmp_path / "note.md").write_text("mine")
    _, first = run(tmp_path, Upper())
    _, second = run(tmp_path, Upper())
    assert (tmp_path / "note.md").read_text() == "mine"
    assert first.name == "note (1).md"
    assert second.name == "note (2).md"


def test_overwrite(tmp_path):
    (tmp_path / "note.md").write_text("mine")
    _, result = run(tmp_path, Upper(), overwrite=True)
    assert result == tmp_path / "note.md"
    assert result.read_text() == "HELLO"


def test_multi_step_route(tmp_path):
    src = tmp_path / "note.txt"
    src.write_text("abc")
    two_steps = Route((Edge("txt", "md", Upper()), Edge("md", "html", Upper())), 2.0)
    with Workspace(tmp_path / "ws") as workspace:
        result = execute(two_steps, src, tmp_path / "out", Context(workspace, Options(), Reporter()))
    assert result == tmp_path / "out" / "note.html"
    assert result.read_text() == "ABC"
    assert [p.name for p in (tmp_path / "out").iterdir()] == ["note.html"]
