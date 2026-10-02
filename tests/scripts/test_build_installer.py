# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
from __future__ import annotations

import re
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


@pytest.fixture(autouse=True)
def _installer_out(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """main() builds into build_windows_app.OUT; keep tests out of the real dist/."""
    out = tmp_path / "installer-out"
    monkeypatch.setattr("build_windows_app.OUT", out)
    return out


def fake_iscc(produce: bool = True, code: int = 0) -> bi.Runner:
    def run(cmd: Sequence[str]) -> tuple[int, str]:
        out_dir = Path(next(a for a in cmd if a.startswith("/DOutputDir=")).split("=", 1)[1])
        run.cmd = list(cmd)  # type: ignore[attr-defined]
        if produce:
            (out_dir / bi.installer_name(__version__)).write_bytes(b"MZ")
        return code, "iscc log"

    return run


@pytest.mark.parametrize(
    ("version", "numeric"),
    [("0.1.2", "0.1.2"), ("0.1.0rc3", "0.1.0"), ("1.2.3.4", "1.2.3.4"), ("2", "2")],
)
def test_numeric_version(version: str, numeric: str) -> None:
    # Inno's VersionInfoVersion takes numbers only; rc tags failed to build (#167).
    assert bi.numeric_version(version) == numeric


def test_numeric_version_rejects_non_numeric() -> None:
    with pytest.raises(ValueError, match="does not start with a number"):
        bi.numeric_version("rc1")


def test_rc_build_passes_full_and_numeric_versions() -> None:
    cmd = bi.iscc_command("ISCC.exe", "0.1.0rc3", {"x64": Path("app")}, Path("out"))
    assert "/DAppVersion=0.1.0rc3" in cmd
    assert "/DAppNumericVersion=0.1.0" in cmd
    iss = bi.ISS.read_text(encoding="utf-8")
    assert "VersionInfoVersion={#AppNumericVersion}" in iss
    assert "OutputBaseFilename=n1mm-scope-bridge-setup-{#AppVersion}" in iss


def test_iscc_command() -> None:
    cmd = bi.iscc_command("ISCC.exe", "1.2.3", {"x64": Path("app")}, Path("out"))
    assert cmd[:2] == ["ISCC.exe", "/Q"]
    assert "/DAppVersion=1.2.3" in cmd
    assert "/DAppNumericVersion=1.2.3" in cmd
    assert f"/DSourceX64={Path('app').absolute()}" in cmd
    assert not any(
        c.startswith(("/DSourceArm64=", "/DSourceX86=", "/DFtdiWheelUrl86=")) for c in cmd
    )
    assert cmd[-1].endswith("installer.iss")
    assert all(Path(c.split("=", 1)[1]).is_absolute() for c in cmd if c.startswith("/DSource"))
    assert any(
        c.startswith("/DFtdiWheelSha256=") and len(c) == len("/DFtdiWheelSha256=") + 64 for c in cmd
    )
    assert any(c.startswith("/DFtdiWheelUrl=https://") for c in cmd)
    assert any(
        c.startswith("/DFtdiDriverUrl=https://catalog.s.download.windowsupdate.com/") for c in cmd
    )
    assert any(c.startswith("/DFtdiDriverSha256=") for c in cmd)


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
    installer = bi.build({"x64": make_app(tmp_path)}, "ISCC.exe", runner)
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
        bi.build({"x64": make_app(tmp_path, **kwargs)}, "ISCC.exe", fake_iscc())  # type: ignore[arg-type]


def test_build_requires_app_folder(tmp_path: Path) -> None:
    with pytest.raises(bi.InstallerError, match=r"run scripts/build_windows_app\.py first"):
        bi.build({"x64": tmp_path / "nope"}, "ISCC.exe", fake_iscc())


def test_build_reports_iscc_failures(tmp_path: Path) -> None:
    with pytest.raises(bi.InstallerError, match=r"ISCC failed \(2\)"):
        bi.build({"x64": make_app(tmp_path / "a")}, "ISCC.exe", fake_iscc(code=2))
    with pytest.raises(bi.InstallerError, match="did not produce"):
        bi.build({"x64": make_app(tmp_path / "b")}, "ISCC.exe", fake_iscc(produce=False))


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
    assert (tmp_path / "installer-out" / bi.installer_name(__version__)).is_file()
    assert "built" in capsys.readouterr().out
    assert (
        bi.main(["--app-dir", str(tmp_path / "nope"), "--iscc", str(iscc)], runner=fake_iscc()) == 1
    )
    assert "error:" in capsys.readouterr().err


def test_installer_script_never_bundles_ftdi() -> None:
    iss = bi.ISS.read_text(encoding="utf-8")
    sources = [line for line in iss.splitlines() if line.startswith("Source:")]
    # The app folders (checked FTDI-free by check_app_dir), the 32-bit start script, and
    # the two helper scripts only: FTDI's DLLs and driver are downloaded (#133, #152).
    assert len(sources) == 6
    for define, payload in (("SourceX64", "x64"), ("SourceArm64", "arm64"), ("SourceX86", "x86")):
        expected = (
            f'Source: "{{#{define}}}\\*"; DestDir: "{{app}}"; Check: IsPayload(\'{payload}\')'
        )
        assert any(line.startswith(expected) for line in sources), expected
    assert 'Source: "cli-start.cmd"; DestDir: "{app}"; Check: IsPayload(\'x86\')' in sources[3]
    assert sources[4] == 'Source: "ftdi_install.ps1"; Flags: dontcopy'
    assert sources[5] == 'Source: "ftdi_driver.ps1"; Flags: dontcopy'
    assert ".cab" not in "".join(sources).lower()
    assert ".dll" not in "".join(sources).lower()
    assert "DownloadTemporaryFile(Url, WheelFile, Sha256, nil)" in iss
    assert "Url := '{#FtdiWheelUrl}'" in iss
    assert "Url := '{#FtdiWheelUrl86}'" in iss
    assert "LicenseFile=..\\..\\LICENSE" in iss
    assert "PrivilegesRequired=lowest" in iss
    # Only the optional driver task elevates, and it's off unless the user ticks it.
    driver_task = next(line for line in iss.splitlines() if line.startswith('Name: "ftdidriver"'))
    assert "Flags: unchecked" in driver_task
    assert "Check: CanInstallFtdiDriver" in driver_task
    # The Microsoft Update Catalog package has x86 and amd64 drivers only (#149).
    can = iss[iss.index("function CanInstallFtdiDriver") :]
    assert "not IsArm64() and FtdiDriverMissing()" in can[: can.index("end;")]
    assert iss.count("ShellExec('runas'") == 1
    drv = "DownloadTemporaryFile('{#FtdiDriverUrl}', '{#FtdiDriverFile}', '{#FtdiDriverSha256}'"
    assert drv in iss


def test_installer_script_supports_every_windows_pc() -> None:
    iss = bi.ISS.read_text(encoding="utf-8")
    assert "ArchitecturesAllowed=x86compatible" in iss
    assert "ArchitecturesInstallIn64BitMode=x64compatible" in iss
    assert "Compression=lzma2/max" in iss
    assert "SolidCompression=yes" in iss
    assert "{param:PAYLOAD|}" in iss
    # The GUI and its shortcuts only where the payload has one (not 32-bit).
    assert 'Filename: "{app}\\{#GuiExe}"; Check: HasGui' in iss
    assert "UninstallDisplayIcon={app}\\{#CliExe}" in iss
    assert (bi.ISS.parent / "cli-start.cmd").read_text(encoding="utf-8").count(
        "run --settings"
    ) == 1


def test_no_blocking_dialogs_in_silent_installs() -> None:
    """Plain MsgBox ignores /SUPPRESSMSGBOXES; every MsgBox path must skip silent mode."""
    iss = bi.ISS.read_text(encoding="utf-8")
    code = iss[iss.index("[Code]") :]
    licence = code[code.index("(CurPageID = wpSelectTasks)") :]
    assert "not WizardSilent()" in licence.splitlines()[0]
    failed = code[code.index("procedure FtdiDownloadFailed") :]
    assert "if not WizardSilent() then" in failed[: failed.index("end;")]


def test_never_starts_with_windows_and_cleans_old_run_value() -> None:
    iss = bi.ISS.read_text(encoding="utf-8")
    assert "autostart" not in iss
    run = [
        line
        for line in iss.splitlines()
        if "CurrentVersion\\Run" in line and not line.startswith(";")
    ]
    assert run == [
        'Root: HKA; Subkey: "Software\\Microsoft\\Windows\\CurrentVersion\\Run"; ValueType: none; '
        'ValueName: "{#AppName}"; Flags: deletevalue uninsdeletevalue'
    ]


def test_ftdi_prompt_names_pypi_and_links_privacy_notice() -> None:
    iss = bi.ISS.read_text(encoding="utf-8")
    assert "Python Package Index (PyPI" in iss
    assert "your IP address" in iss
    assert '#define PrivacyUrl "https://reid-n0rc.github.io/n1mm-scope-bridge/privacy.html"' in iss
    assert "{#PrivacyUrl}" in iss


# --- one installer, three payloads (#149) -------------------------------------------------


def make_cli_app(tmp_path: Path) -> Path:
    return make_app(tmp_path, drop="N1MM Scope Bridge.exe")


def test_iscc_command_with_every_payload() -> None:
    apps = {"x64": Path("a64"), "arm64": Path("aarm"), "x86": Path("a86")}
    cmd = bi.iscc_command("ISCC.exe", "1.2.3", apps, Path("out"))
    assert f"/DSourceX64={Path('a64').absolute()}" in cmd
    assert f"/DSourceArm64={Path('aarm').absolute()}" in cmd
    assert f"/DSourceX86={Path('a86').absolute()}" in cmd
    defines = dict(c[2:].split("=", 1) for c in cmd if c.startswith("/DFtdi"))
    assert defines["FtdiWheelFile86"].endswith("-win32.whl")
    assert len(defines["FtdiWheelSha25686"]) == 64
    assert defines["FtdiLibSigner86"] == "Future Technology Devices International"


def test_x86_payload_needs_no_gui_exe(tmp_path: Path) -> None:
    apps = {"x64": make_app(tmp_path / "x64"), "x86": make_cli_app(tmp_path / "x86")}
    runner = fake_iscc()
    bi.build(apps, "ISCC.exe", runner)
    assert any(c.startswith("/DSourceX86=") for c in runner.cmd)  # type: ignore[attr-defined]


def test_x64_payload_still_needs_the_gui(tmp_path: Path) -> None:
    with pytest.raises(bi.InstallerError, match=r"missing: N1MM Scope Bridge\.exe"):
        bi.build({"x64": make_cli_app(tmp_path)}, "ISCC.exe", fake_iscc())


def test_require_all_payloads_for_releases(tmp_path: Path) -> None:
    with pytest.raises(bi.InstallerError, match=r"missing: \['arm64', 'x86'\]"):
        bi.build({"x64": make_app(tmp_path)}, "ISCC.exe", fake_iscc(), require_all=True)


@pytest.mark.parametrize(
    ("apps", "message"), [({}, "no app folders"), ({"mips": Path("m")}, "unknown")]
)
def test_bad_payload_sets(apps: dict[str, Path], message: str) -> None:
    with pytest.raises(bi.InstallerError, match=message):
        bi.build(apps, "ISCC.exe", fake_iscc())


def test_main_with_every_payload(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    iscc = tmp_path / "ISCC.exe"
    iscc.write_bytes(b"x")
    args = ["--app-dir", str(make_app(tmp_path / "x64")),
            "--app-arm64", str(make_app(tmp_path / "arm")),
            "--app-x86", str(make_cli_app(tmp_path / "x86")),
            "--require-all", "--iscc", str(iscc)]  # fmt: skip
    assert bi.main(args, runner=fake_iscc()) == 0
    assert "payloads: x64, arm64, x86" in capsys.readouterr().out


@pytest.mark.parametrize(("arch", "payload"), [("x64", "x64"), ("ARM64", "arm64"), ("x86", "x86")])
def test_main_default_uses_the_local_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    arch: str, payload: str,
) -> None:  # fmt: skip
    app_dir = (
        make_app(tmp_path / "dist" / "windows")
        if arch != "x86"
        else make_cli_app(tmp_path / "dist" / "windows")
    )
    monkeypatch.setattr(bi, "APP_DIR", app_dir)
    monkeypatch.setattr("build_windows_app.build_arch", lambda platform_tag=None: arch)
    iscc = tmp_path / "ISCC.exe"
    iscc.write_bytes(b"x")
    assert bi.main(["--iscc", str(iscc)], runner=fake_iscc()) == 0
    assert f"payloads: {payload}" in capsys.readouterr().out


def test_no_code_line_starts_with_a_character_constant() -> None:
    """ISPP reads a line starting with "#13#10" as an unknown preprocessor directive.

    (#ifdef lines inside [Code] are intended: they select the payloads.)
    """
    lines = bi.ISS.read_text(encoding="utf-8").splitlines()
    assert not [line for line in lines if re.match(r"\s*#\d", line)]
