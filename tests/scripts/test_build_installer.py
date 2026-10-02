# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import build_installer as bi
import fetch_ftdi
import pytest

from n1mm_scope_bridge import __version__


def make_app(tmp_path: Path, extra: Sequence[str] = (), drop: str = "") -> Path:
    app_dir = tmp_path / "windows" / "n1mm-scope-bridge"
    for rel in [r for r in bi.REQUIRED if r != drop] + list(extra):
        (app_dir / rel).parent.mkdir(parents=True, exist_ok=True)
        (app_dir / rel).write_bytes(b"x")
    return app_dir


def fake_iscc(produce: bool = True, code: int = 0) -> bi.Runner:
    def run(cmd: Sequence[str]) -> tuple[int, str]:
        out_dir = Path(next(a for a in cmd if a.startswith("/DOutputDir=")).split("=", 1)[1])
        run.cmd = list(cmd)  # type: ignore[attr-defined]
        if produce:
            (out_dir / bi.installer_name(__version__)).write_bytes(b"MZ")
        return code, "iscc log"

    return run


def test_iscc_command() -> None:
    cmd = bi.iscc_command("ISCC.exe", "1.2.3", Path("app"), Path("out"))
    assert cmd[:2] == ["ISCC.exe", "/Q"]
    assert "/DAppVersion=1.2.3" in cmd
    assert f"/DSourceDir={Path('app')}" in cmd
    assert cmd[-1].endswith("installer.iss")
    assert any(
        c.startswith("/DFtdiWheelSha256=") and len(c) == len("/DFtdiWheelSha256=") + 64 for c in cmd
    )
    assert any(c.startswith("/DFtdiWheelUrl=https://") for c in cmd)


def test_ftdi_defines_follow_the_pin() -> None:
    defines = dict(d[2:].split("=", 1) for d in bi.ftdi_defines())
    pkg, signers = fetch_ftdi.load_pin()
    assert defines["FtdiWheelUrl"] == pkg.url
    assert defines["FtdiWheelFile"] == pkg.filename
    assert defines["FtdiLibSigner"] == signers["LibFT4222-64.dll"]
    assert defines["FtdiLicenceUrl"].startswith("https://")


def test_installer_name() -> None:
    assert bi.installer_name("0.1.0") == "n1mm-scope-bridge-setup-0.1.0.exe"


def test_build_success(tmp_path: Path) -> None:
    runner = fake_iscc()
    installer = bi.build(make_app(tmp_path), "ISCC.exe", runner)
    assert installer.name == bi.installer_name(__version__)
    assert f"/DAppVersion={__version__}" in runner.cmd  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"drop": "N1MM Scope Bridge.exe"}, "missing: N1MM Scope Bridge.exe"),
        ({"drop": "licenses/NOTICE"}, "missing: licenses/NOTICE"),
        ({"extra": ["_internal/LibFT4222-64.dll"]}, "must never be bundled"),
    ],
)
def test_build_checks_app_folder(tmp_path: Path, kwargs: dict[str, object], message: str) -> None:
    with pytest.raises(bi.InstallerError, match=message):
        bi.build(make_app(tmp_path, **kwargs), "ISCC.exe", fake_iscc())  # type: ignore[arg-type]


def test_build_requires_app_folder(tmp_path: Path) -> None:
    with pytest.raises(bi.InstallerError, match=r"run scripts/build_windows_app\.py first"):
        bi.build(tmp_path / "nope", "ISCC.exe", fake_iscc())


def test_build_reports_iscc_failures(tmp_path: Path) -> None:
    with pytest.raises(bi.InstallerError, match=r"ISCC failed \(2\)"):
        bi.build(make_app(tmp_path / "a"), "ISCC.exe", fake_iscc(code=2))
    with pytest.raises(bi.InstallerError, match="did not produce"):
        bi.build(make_app(tmp_path / "b"), "ISCC.exe", fake_iscc(produce=False))


def test_find_iscc_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("build_installer.shutil.which", lambda _: None)  # runners have ISCC on PATH
    explicit = tmp_path / "explicit" / "ISCC.exe"
    from_env = tmp_path / "env" / "ISCC.exe"
    default = tmp_path / "pf" / "Inno Setup 7" / "ISCC.exe"
    for p in (explicit, from_env, default):
        p.parent.mkdir(parents=True)
        p.write_bytes(b"x")
    env = {"ISCC": str(from_env), "ProgramFiles": str(tmp_path / "pf")}
    assert bi.find_iscc(str(explicit), env) == str(explicit)
    assert bi.find_iscc(None, env) == str(from_env)
    assert bi.find_iscc(None, {"ProgramFiles": str(tmp_path / "pf")}) == str(default)


def test_find_iscc_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("build_installer.shutil.which", lambda _: None)
    with pytest.raises(bi.InstallerError, match=r"ISCC\.exe not found"):
        bi.find_iscc(None, {"ProgramFiles": str(tmp_path)})


def test_main(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    app_dir = make_app(tmp_path)
    iscc = tmp_path / "ISCC.exe"
    iscc.write_bytes(b"x")
    assert bi.main(["--app-dir", str(app_dir), "--iscc", str(iscc)], runner=fake_iscc()) == 0
    assert "built" in capsys.readouterr().out
    assert (
        bi.main(["--app-dir", str(tmp_path / "nope"), "--iscc", str(iscc)], runner=fake_iscc()) == 1
    )
    assert "error:" in capsys.readouterr().err


def test_installer_script_never_bundles_ftdi() -> None:
    iss = bi.ISS.read_text(encoding="utf-8")
    sources = [line for line in iss.splitlines() if line.startswith("Source:")]
    # The app folder (checked FTDI-free by check_app_dir) plus the helper script only:
    # FTDI's DLLs are downloaded at install time, never packed into the installer (#133).
    assert len(sources) == 2
    assert sources[0].startswith('Source: "{#SourceDir}\\*"; DestDir: "{app}"')
    assert sources[1] == 'Source: "ftdi_install.ps1"; Flags: dontcopy'
    assert ".dll" not in "".join(sources).lower()
    assert "DownloadTemporaryFile('{#FtdiWheelUrl}', '{#FtdiWheelFile}', '{#FtdiWheelSha256}'" in iss
    assert "LicenseFile=..\\..\\LICENSE" in iss
    assert "PrivilegesRequired=lowest" in iss
