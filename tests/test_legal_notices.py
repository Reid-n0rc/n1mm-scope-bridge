# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""The non-affiliation disclaimer appears, verbatim, everywhere it should (#140)."""

from __future__ import annotations

import html
import io
from pathlib import Path

import build_site as bs
import pytest

from n1mm_scope_bridge.cli import LEGAL_NOTICE, LICENSE_TEXT, main
from n1mm_scope_bridge.legal import DISCLAIMER, SHORT_DISCLAIMER

ROOT = Path(__file__).resolve().parent.parent


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def flat(s: str) -> str:
    return " ".join(s.split())


@pytest.mark.parametrize(
    "path", ["docs/legal-notices.md", "README.md", "docs/user/README.md", "NOTICE"]
)
def test_full_disclaimer_is_verbatim(path: str) -> None:
    assert DISCLAIMER in flat(text(path))


def test_short_form_in_legal_notices_and_third_party() -> None:
    assert SHORT_DISCLAIMER in text("docs/legal-notices.md")
    assert SHORT_DISCLAIMER in text("THIRD_PARTY.md")


def test_disclaimer_names_everyone() -> None:
    for name in ("N1MM Logger+", "N1MM.", "Yaesu", "FTDI", "wfview"):
        assert name in DISCLAIMER
    for name in ("N1MM Logger+", "N1MM,", "Yaesu", "FTDI", "wfview"):
        assert name in SHORT_DISCLAIMER


def test_site_about_and_footer() -> None:
    assert DISCLAIMER in flat(html.unescape(text("site/about.html")))
    assert SHORT_DISCLAIMER in text("site/_partials/footer.html")
    assert bs.DISCLAIMER_MARKER in SHORT_DISCLAIMER


def test_real_site_build_puts_disclaimer_on_every_page(tmp_path: Path) -> None:
    pages = bs.build(tmp_path / "out", bs.context(None, None))
    assert pages
    for page in pages:
        assert SHORT_DISCLAIMER in page.read_text(encoding="utf-8"), page.name


def test_site_build_fails_when_a_page_lacks_the_footer(tmp_path: Path) -> None:
    src = tmp_path / "src"
    (src / bs.PARTIALS).mkdir(parents=True)
    (src / bs.PARTIALS / "footer.html").write_text(f"<p>{SHORT_DISCLAIMER}</p>", encoding="utf-8")
    (src / "a.html").write_text("<!-- include:footer -->", encoding="utf-8")
    (src / "b.html").write_text("<p>no footer</p>", encoding="utf-8")
    with pytest.raises(bs.SiteError, match=r"b\.html: missing the non-affiliation disclaimer"):
        bs.build(tmp_path / "out", bs.context(None, None), src)


def test_cli_version_and_license_show_disclaimer(capsys: pytest.CaptureFixture[str]) -> None:
    assert SHORT_DISCLAIMER in LEGAL_NOTICE
    assert DISCLAIMER in LICENSE_TEXT
    with pytest.raises(SystemExit):
        main(["--version"], out=io.StringIO(), err=io.StringIO())
    assert SHORT_DISCLAIMER in capsys.readouterr().out
