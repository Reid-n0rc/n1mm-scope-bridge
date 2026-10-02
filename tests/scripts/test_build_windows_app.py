# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
from __future__ import annotations

import ast
import socket
import zipfile
from collections.abc import Sequence
from pathlib import Path

import build_windows_app as bw
import pytest

from n1mm_scope_bridge import __version__

SPECTRUM = b'<?xml version="1.0" encoding="utf-8"?>\n<Spectrum>\n</Spectrum>'


def test_read_version_matches_package() -> None:
    assert bw.read_version() == __version__


def test_read_version_missing(tmp_path: Path) -> None:
    init = tmp_path / "__init__.py"
    init.write_text("x = 1\n", encoding="utf-8")
    with pytest.raises(bw.BuildError, match="no __version__"):
        bw.read_version(init)


@pytest.mark.parametrize(
    ("version", "expected"),
    [("0.1.0", (0, 1, 0, 0)), ("1.2.3rc1", (1, 2, 3, 0)), ("2.0", (2, 0, 0, 0)),
     ("1.2.3.4.5", (1, 2, 3, 4)), ("3.1.0.dev2", (3, 1, 0, 0))],
)  # fmt: skip
def test_version_tuple(version: str, expected: tuple[int, int, int, int]) -> None:
    assert bw.version_tuple(version) == expected


def test_version_tuple_rejects_garbage() -> None:
    with pytest.raises(bw.BuildError, match="Windows version"):
        bw.version_tuple("banana")


def test_version_info_text_is_a_valid_python_literal() -> None:
    text = bw.version_info_text("1.2.3rc1")
    tree = ast.parse(text, mode="eval")
    assert isinstance(tree.body, ast.Call)
    assert "filevers=(1, 2, 3, 0)" in text
    assert "'ProductVersion', '1.2.3rc1'" in text
    assert "GPL-3.0-only" in text


@pytest.mark.parametrize(
    ("paths", "bad"),
    [
        (["n1mm-scope-bridge.exe", "_internal/python313.dll"], []),
        (["_internal/LibFT4222-64.dll"], ["_internal/LibFT4222-64.dll"]),
        (["x/FTD2XX.DLL", "y/libft4222.so.1.4"], ["x/FTD2XX.DLL", "y/libft4222.so.1.4"]),
        (["ft4222.py"], []),
    ],
)
def test_find_forbidden(paths: list[str], bad: list[str]) -> None:
    assert bw.find_forbidden(paths) == sorted(bad)


def test_collect_licenses(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    for name in bw.LICENSE_FILES:
        (root / name).write_text(name, encoding="utf-8")
    qt = tmp_path / "PySide6_Essentials-6.11.dist-info" / "LICENSE"
    qt.parent.mkdir()
    qt.write_text("qt", encoding="utf-8")
    copied = bw.collect_licenses(tmp_path / "app", qt_files=[qt], root=root)
    names = sorted(p.relative_to(tmp_path / "app").as_posix() for p in copied)
    assert names == [
        "licenses/LICENSE",
        "licenses/NOTICE",
        "licenses/THIRD_PARTY.md",
        "licenses/qt/PySide6_Essentials-6.11.dist-info-LICENSE",
    ]


def test_collect_licenses_requires_files(tmp_path: Path) -> None:
    with pytest.raises(bw.BuildError, match="missing LICENSE"):
        bw.collect_licenses(tmp_path / "app", root=tmp_path)


def test_zip_contents_and_name(tmp_path: Path) -> None:
    app = tmp_path / "n1mm-scope-bridge"
    (app / "licenses").mkdir(parents=True)
    (app / "n1mm-scope-bridge.exe").write_bytes(b"MZ")
    (app / "licenses" / "LICENSE").write_text("gpl", encoding="utf-8")
    out = bw.make_zip(app, tmp_path / bw.zip_name("0.1.0"))
    assert out.name == "n1mm-scope-bridge-0.1.0-win64.zip"
    with zipfile.ZipFile(out) as zf:
        assert sorted(zf.namelist()) == [
            "n1mm-scope-bridge/licenses/LICENSE",
            "n1mm-scope-bridge/n1mm-scope-bridge.exe",
        ]


def test_exe_path() -> None:
    assert bw.exe_path(Path("a"), windows=True) == Path("a/n1mm-scope-bridge.exe")
    assert bw.exe_path(Path("a"), "N1MM Scope Bridge", windows=False) == Path("a/N1MM Scope Bridge")


# --- smoke test ----------------------------------------------------------------------


def fake_app(
    *, version_out: str = "ABSOLUTELY NO WARRANTY", license_out: str = "corresponding source",
    run_code: int = 0, packets: int = 5, packet: bytes = SPECTRUM,
) -> bw.Runner:  # fmt: skip
    def run(cmd: Sequence[str], env: dict[str, str] | None) -> tuple[int, str]:
        if cmd[-1] == "--version":
            return 0, version_out
        if cmd[-1] == "--license":
            return 0, license_out
        port = int(cmd[cmd.index("--port") + 1])
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as tx:
            for _ in range(packets):
                tx.sendto(packet, ("127.0.0.1", port))
        return run_code, "log"

    return run


def test_smoke_test_passes() -> None:
    bw.smoke_test(Path("app.exe"), fake_app())


@pytest.mark.parametrize(
    ("kw", "message"),
    [
        ({"version_out": "0.1.0"}, "--version failed"),
        ({"license_out": "nope"}, "--license failed"),
        ({"run_code": 1}, "run --emulator failed"),
        ({"packets": 1}, "sent 1 packets"),
        ({"packet": b"<Other/>"}, "not <Spectrum>"),
    ],
)
def test_smoke_test_failures(kw: dict[str, object], message: str) -> None:
    with pytest.raises(bw.BuildError, match=message):
        bw.smoke_test(Path("app.exe"), fake_app(**kw))  # type: ignore[arg-type]


# --- build orchestration --------------------------------------------------------------


def fake_pyinstaller(files: Sequence[str], code: int = 0) -> bw.Runner:
    """Pretends to be PyInstaller: creates ``files`` in the app folder."""

    def run(cmd: Sequence[str], env: dict[str, str] | None) -> tuple[int, str]:
        assert cmd[0] == "pyinstaller"
        assert env is not None
        assert (
            Path(env["N1MM_VERSION_FILE"]).read_text(encoding="utf-8").startswith("VSVersionInfo")
        )
        app = Path(cmd[cmd.index("--distpath") + 1]) / bw.APP_NAME
        app.mkdir(parents=True, exist_ok=True)
        for name in files:
            (app / name).parent.mkdir(parents=True, exist_ok=True)
            (app / name).write_bytes(b"x")
        run.gui = env["N1MM_BUILD_GUI"]  # type: ignore[attr-defined]
        return code, "pyinstaller log"

    return run


def test_build_cli_only(tmp_path: Path) -> None:
    runner = fake_pyinstaller(["n1mm-scope-bridge.exe"])
    out = bw.build(
        gui=False, out=tmp_path / "dist", work=tmp_path / "w", smoke=False, runner=runner
    )
    assert out.name.endswith("-win64.zip")
    assert runner.gui == "0"  # type: ignore[attr-defined]
    with zipfile.ZipFile(out) as zf:
        assert "n1mm-scope-bridge/licenses/NOTICE" in zf.namelist()


def test_build_with_gui_requires_gui_exe(tmp_path: Path) -> None:
    ok = fake_pyinstaller(["n1mm-scope-bridge.exe", "N1MM Scope Bridge.exe", "N1MM Scope Bridge"])
    bw.build(
        gui=True, out=tmp_path / "d1", work=tmp_path / "w", smoke=False, runner=ok, qt_files=list
    )
    missing = fake_pyinstaller(["n1mm-scope-bridge.exe"])
    with pytest.raises(bw.BuildError, match="was not built"):
        bw.build(gui=True, out=tmp_path / "d2", work=tmp_path / "w", smoke=False, runner=missing,
                 qt_files=list)  # fmt: skip


def test_build_refuses_ftdi_binaries(tmp_path: Path) -> None:
    runner = fake_pyinstaller(["n1mm-scope-bridge.exe", "_internal/LibFT4222-64.dll"])
    with pytest.raises(bw.BuildError, match="must never be bundled"):
        bw.build(gui=False, out=tmp_path / "d", work=tmp_path / "w", smoke=False, runner=runner)


def test_build_reports_pyinstaller_failure(tmp_path: Path) -> None:
    with pytest.raises(bw.BuildError, match="PyInstaller failed"):
        bw.build(gui=False, out=tmp_path / "d", work=tmp_path / "w", smoke=False,
                 runner=fake_pyinstaller([], code=1))  # fmt: skip


def test_build_runs_smoke_test(tmp_path: Path) -> None:
    pyi = fake_pyinstaller(["n1mm-scope-bridge.exe", "n1mm-scope-bridge"])
    app = fake_app()

    def runner(cmd: Sequence[str], env: dict[str, str] | None) -> tuple[int, str]:
        return pyi(cmd, env) if cmd[0] == "pyinstaller" else app(cmd, env)

    bw.build(gui=False, out=tmp_path / "d", work=tmp_path / "w", smoke=True, runner=runner)


def test_main_refuses_non_windows_without_flag(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("build_windows_app.sys.platform", "linux")
    assert bw.main([]) == 2
    assert "build on Windows" in capsys.readouterr().err


def test_main_reports_build_errors(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.setattr(bw, "OUT", tmp_path / "d")
    monkeypatch.setattr(bw, "WORK", tmp_path / "w")
    code = bw.main(["--allow-non-windows", "--no-smoke", "--gui", "off"],
                   runner=fake_pyinstaller([], code=3))  # fmt: skip
    assert code == 1
    assert "PyInstaller failed (3)" in capsys.readouterr().err


def test_main_success(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.setattr(bw, "OUT", tmp_path / "dist")
    monkeypatch.setattr(bw, "WORK", tmp_path / "w")
    monkeypatch.setattr(bw, "GUI_MODULE", tmp_path / "missing_app.py")
    code = bw.main(["--allow-non-windows", "--no-smoke"],
                   runner=fake_pyinstaller(["n1mm-scope-bridge.exe"]))  # fmt: skip
    assert code == 0
    assert "(GUI exe: no)" in capsys.readouterr().out


def test_gui_self_test_passes_and_enables_qt_plugin_debugging() -> None:
    seen: dict[str, str] = {}

    def run(cmd: Sequence[str], env: dict[str, str] | None) -> tuple[int, str]:
        assert cmd[-1] == "--self-test"
        seen.update(env or {})
        return 0, "self-test: OK"

    bw.gui_self_test(Path("N1MM Scope Bridge.exe"), run)
    assert seen["QT_DEBUG_PLUGINS"] == "1"


def test_gui_self_test_failure_includes_output() -> None:
    def run(cmd: Sequence[str], env: dict[str, str] | None) -> tuple[int, str]:
        return 124, "timed out\nqt.qpa.plugin: Could not find the Qt platform plugin"

    with pytest.raises(bw.BuildError, match="platform plugin"):
        bw.gui_self_test(Path("N1MM Scope Bridge.exe"), run)


def test_build_with_gui_runs_gui_self_test(tmp_path: Path) -> None:
    pyi = fake_pyinstaller(["n1mm-scope-bridge.exe", "n1mm-scope-bridge",
                            "N1MM Scope Bridge.exe", "N1MM Scope Bridge"])  # fmt: skip
    app = fake_app()
    gui_runs: list[str] = []

    def runner(cmd: Sequence[str], env: dict[str, str] | None) -> tuple[int, str]:
        if cmd[0] == "pyinstaller":
            return pyi(cmd, env)
        if cmd[-1] == "--self-test":
            gui_runs.append(cmd[0])
            return 0, "self-test: OK"
        return app(cmd, env)

    bw.build(gui=True, out=tmp_path / "d", work=tmp_path / "w", smoke=True, runner=runner,
             qt_files=list)  # fmt: skip
    assert len(gui_runs) == 1


# --- architectures (#149) ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("tag", "arch"),
    [("win-amd64", "x64"), ("win-arm64", "ARM64"), ("win32", "x86"), ("linux-x86_64", "x64")],
)
def test_build_arch(tag: str, arch: str) -> None:
    assert bw.build_arch(tag) == arch


@pytest.mark.parametrize(
    ("arch", "suffix"), [("x64", "win64"), ("ARM64", "winarm64"), ("x86", "win32")]
)
def test_zip_name_per_arch(arch: str, suffix: str) -> None:
    assert bw.zip_name("0.1.0", arch) == f"n1mm-scope-bridge-0.1.0-{suffix}.zip"
    assert bw.zip_name("0.1.0") == "n1mm-scope-bridge-0.1.0-win64.zip"


def test_x86_builds_the_command_line_app_only(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.setattr(bw, "OUT", tmp_path / "dist")
    monkeypatch.setattr(bw, "WORK", tmp_path / "w")
    monkeypatch.setattr(bw, "build_arch", lambda platform_tag=None: "x86")
    code = bw.main(["--allow-non-windows", "--no-smoke"],
                   runner=fake_pyinstaller(["n1mm-scope-bridge.exe"]))  # fmt: skip
    assert code == 0
    out = capsys.readouterr().out
    assert "-win32.zip for x86 (GUI exe: no)" in out


def test_x86_refuses_an_explicit_gui_build(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(bw, "build_arch", lambda platform_tag=None: "x86")
    assert bw.main(["--allow-non-windows", "--gui", "on"]) == 2
    assert "needs 64-bit Windows" in capsys.readouterr().err
