import json

from transcript.cli import main


def test_help_without_arguments(capsys):
    assert main([]) == 0
    assert "transcript" in capsys.readouterr().out


def test_missing_file(tmp_path):
    assert main([str(tmp_path / "nope.docx"), "--to", "pdf"]) == 2


def test_list_targets(tmp_path, capsys):
    src = tmp_path / "data.json"
    src.write_text('{"a": 1}')
    assert main([str(src), "--list"]) == 0
    out = capsys.readouterr().out
    assert "yaml" in out and "toml" in out and "Data" in out


def test_non_interactive_needs_a_target(tmp_path, capsys):
    src = tmp_path / "data.json"
    src.write_text('{"a": 1}')
    assert main([str(src)]) == 2
    assert "--to" in capsys.readouterr().err


def test_unknown_and_impossible_targets(tmp_path):
    src = tmp_path / "data.json"
    src.write_text('{"a": 1}')
    assert main([str(src), "--to", "klingon"]) == 2
    assert main([str(src), "--to", "mp3"]) == 2


def test_target_by_extension_and_from_override(tmp_path):
    src = tmp_path / "settings.conf"
    src.write_text("a: 1\nb: [x, y]\n")
    assert main([str(src), "--from", "yaml", "--to", ".json"]) == 0
    assert json.loads((tmp_path / "settings.json").read_text()) == {"a": 1, "b": ["x", "y"]}


def test_batch(tmp_path):
    first = tmp_path / "one.json"
    second = tmp_path / "two.yaml"
    first.write_text('{"n": 1}')
    second.write_text("n: 2\n")
    assert main([str(first), str(second), "--to", "toml"]) == 0
    assert (tmp_path / "one.toml").read_text().strip() == "n = 1"
    assert (tmp_path / "two.toml").read_text().strip() == "n = 2"


def test_failed_conversion_returns_error(tmp_path):
    src = tmp_path / "broken.json"
    src.write_text("{not json")
    assert main([str(src), "--to", "yaml"]) == 1
    assert not (tmp_path / "broken.yaml").exists()


def test_doctor_and_formats(capsys):
    assert main(["--doctor"]) == 0
    assert main(["--formats"]) == 0
    out = capsys.readouterr().out
    assert "Pillow" in out and "docx" in out
