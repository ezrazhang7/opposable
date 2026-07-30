"""Dotenv loader: parsing, precedence, upward search."""

import os

from opposable.env import load_env_files, parse_env_file


def test_parse_env_file(tmp_path):
    f = tmp_path / ".env"
    f.write_text(
        "# comment\n"
        "\n"
        "PLAIN=value\n"
        "export EXPORTED=yes\n"
        'QUOTED="with spaces"\n'
        "SINGLE='single'\n"
        "INLINE=value  # trailing comment\n"
        "EMPTY=\n"
        "not-a-kv-line\n"
    )
    assert parse_env_file(f) == {
        "PLAIN": "value",
        "EXPORTED": "yes",
        "QUOTED": "with spaces",
        "SINGLE": "single",
        "INLINE": "value",
        "EMPTY": "",
    }


def test_precedence_and_upward_search(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("OPPOSABLE_TEST_A=from_env\nOPPOSABLE_TEST_B=from_env\n")
    (tmp_path / ".env.local").write_text("OPPOSABLE_TEST_A=from_local\nOPPOSABLE_TEST_C=from_local\n")
    subdir = tmp_path / "sub" / "deeper"
    subdir.mkdir(parents=True)

    monkeypatch.delenv("OPPOSABLE_TEST_A", raising=False)
    monkeypatch.setenv("OPPOSABLE_TEST_B", "from_shell")
    monkeypatch.delenv("OPPOSABLE_TEST_C", raising=False)

    loaded = load_env_files(start=subdir)  # found by walking up from subdir

    assert os.environ["OPPOSABLE_TEST_A"] == "from_local"  # .env.local beats .env
    assert os.environ["OPPOSABLE_TEST_B"] == "from_shell"  # real env never overwritten
    assert os.environ["OPPOSABLE_TEST_C"] == "from_local"
    assert loaded == {"OPPOSABLE_TEST_A": "from_local", "OPPOSABLE_TEST_C": "from_local"}
    for key in ("OPPOSABLE_TEST_A", "OPPOSABLE_TEST_C"):
        monkeypatch.delenv(key)


def test_no_env_files_is_noop(tmp_path):
    assert load_env_files(start=tmp_path) == {}
