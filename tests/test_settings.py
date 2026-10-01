# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
from __future__ import annotations

import json
from pathlib import Path

import pytest

from n1mm_scope_bridge import settings as st
from n1mm_scope_bridge.settings import Settings


def test_defaults_are_valid_and_match_cli_defaults() -> None:
    s = Settings()
    assert s.validate() == {}
    assert (s.radio, s.n1mm_host, s.n1mm_port, s.on_close) == ("ft710", "127.0.0.1", 13064, "ask")
    assert s.effective_name() == "FT-710"
    config = s.to_bridge_config()
    assert (config.name, config.rate_hz, config.combine) == ("FT-710", 4.0, "latest")


def test_custom_source_name() -> None:
    assert Settings(source_name="Shack").effective_name() == "Shack"
    assert Settings(radio="nope").effective_name() == "nope"


@pytest.mark.parametrize(
    ("change", "field"),
    [
        ({"radio": "ic7300"}, "radio"),
        ({"source_name": " padded "}, "source_name"),
        ({"source_name": "bad\nname"}, "source_name"),
        ({"n1mm_host": " "}, "n1mm_host"),
        ({"n1mm_port": 0}, "n1mm_port"),
        ({"n1mm_port": 65536}, "n1mm_port"),
        ({"rate_hz": 0.0}, "rate_hz"),
        ({"rate_hz": 10.5}, "rate_hz"),
        ({"scaling": 0.0}, "scaling"),
        ({"combine": "median"}, "combine"),
        ({"on_close": "minimize"}, "on_close"),
        ({"ftdi_lib_dir": "/definitely/not/here"}, "ftdi_lib_dir"),
    ],
)
def test_validation_reports_each_field(change: dict[str, object], field: str) -> None:
    problems = Settings().replace(**change).validate()
    assert field in problems
    assert problems[field]


def test_existing_ftdi_folder_is_valid(tmp_path: Path) -> None:
    assert Settings(ftdi_lib_dir=str(tmp_path)).validate() == {}


def test_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "sub" / "settings.json"
    original = Settings(source_name="Shack", n1mm_port=12060, rate_hz=5.0, on_close="tray")
    assert st.save(original, path) == path
    loaded, warnings = st.load(path)
    assert loaded == original
    assert warnings == []
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["version"] == st.SCHEMA_VERSION


def test_missing_file_gives_defaults(tmp_path: Path) -> None:
    assert st.load(tmp_path / "none.json") == (Settings(), [])


@pytest.mark.parametrize("content", ["{not json", "[1, 2]", ""])
def test_corrupt_file_is_backed_up(tmp_path: Path, content: str) -> None:
    path = tmp_path / "settings.json"
    path.write_text(content, encoding="utf-8")
    loaded, warnings = st.load(path)
    assert loaded == Settings()
    assert "unreadable" in warnings[0]
    assert (tmp_path / "settings.json.bak").read_text(encoding="utf-8") == content
    assert not path.exists()


def test_unknown_keys_ignored_and_bad_types_defaulted() -> None:
    loaded, warnings = Settings.from_dict(
        {
            "version": 99,
            "future_option": True,
            "n1mm_port": "13064",
            "rate_hz": 5,
            "scaling": True,
            "start_minimized": 1,
            "source_name": 7,
            "on_close": "tray",
        }
    )
    assert loaded.rate_hz == 5.0
    assert isinstance(loaded.rate_hz, float)
    assert loaded.on_close == "tray"
    assert (loaded.n1mm_port, loaded.scaling, loaded.start_minimized, loaded.source_name) == (
        13064,
        0.3125,
        False,
        "",
    )
    assert len(warnings) == 4
    assert all("ignored invalid" in w for w in warnings)


def test_save_is_atomic_on_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "settings.json"
    st.save(Settings(source_name="kept"), path)

    def boom(*_: object, **__: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("n1mm_scope_bridge.settings.json.dump", boom)
    with pytest.raises(OSError, match="disk full"):
        st.save(Settings(source_name="lost"), path)
    assert st.load(path)[0].source_name == "kept"
    assert [p.name for p in tmp_path.iterdir()] == ["settings.json"]


@pytest.mark.parametrize(
    ("platform", "env", "expected"),
    [
        ("win32", {"APPDATA": "C:/Users/op/AppData/Roaming"}, "C:/Users/op/AppData/Roaming"),
        ("win32", {}, "HOME/AppData/Roaming"),
        ("darwin", {}, "HOME/Library/Application Support"),
        ("linux", {"XDG_CONFIG_HOME": "/xdg"}, "/xdg"),
        ("linux", {}, "HOME/.config"),
    ],
)
def test_settings_path(platform: str, env: dict[str, str], expected: str) -> None:
    home = Path("HOME")
    path = st.settings_path(env, platform, home)
    assert path == Path(expected) / "n1mm-scope-bridge" / "settings.json"


def test_settings_path_defaults_to_current_environment() -> None:
    assert st.settings_path().name == "settings.json"
