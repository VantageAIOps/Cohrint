"""
test_xss_regression.py — Chart.js XSS Regression Guard
=======================================================
Suite FC (XSS): Pins the escaping of untrusted strings that flow into
Chart.js `labels` arrays on the dashboard. Chart.js renders legends and
tooltips via innerHTML-equivalent paths, so an unescaped team/model/month
label from an attacker-controlled org could execute JS in another viewer's
browser.

The audit that motivated this suite:
  - app.html:3425 (team pie)            labels derived from API team.name
  - app.html:3661 (provider breakdown)   labels derived from meta[p].label
  - app.html:5754 (optimization trend)   labels derived from API r.month

All three must route user-supplied strings through esc(...) before
handing them to Chart.js.

Labels: FC.XSS.01 – FC.XSS.05
"""

from pathlib import Path

import pytest

from helpers.output import chk, section, info

APP_HTML = Path(__file__).parent.parent.parent.parent / "cohrint-frontend" / "app.html"


@pytest.fixture(scope="module")
def html() -> str:
    assert APP_HTML.exists(), f"app.html missing at {APP_HTML}"
    return APP_HTML.read_text()


def test_fc_xss_01_esc_helper_present(html):
    """FC.XSS.01 — esc() HTML-escape helper exists and uses textContent (safe)."""
    section("FC.XSS — Chart.js label XSS regression")
    chk("FC.XSS.01 esc() helper exists in app.html",
        "function esc(" in html, "missing esc() helper")
    # textContent-then-innerHTML is the canonical DOM-escape pattern.
    chk("FC.XSS.01b esc() uses textContent-based escaping",
        "d.textContent = String(s)" in html and "return d.innerHTML" in html,
        "esc() body does not match the safe pattern")


def test_fc_xss_02_team_pie_labels_escaped(html):
    """FC.XSS.02 — renderTeamPie wraps team labels with esc()."""
    # Find the renderTeamPie block so we match only the labels line inside it.
    marker = "_teamPieChart = new Chart"
    idx = html.find(marker)
    assert idx >= 0, "renderTeamPie chart block not found"
    window = html[idx:idx + 800]
    chk("FC.XSS.02 team pie labels call esc()",
        "labels: data.map(function(t) { return esc(" in window,
        f"team labels not escaped. window:\n{window[:400]}")


def test_fc_xss_03_provider_breakdown_labels_escaped(html):
    """FC.XSS.03 — renderProviderBreakdown wraps provider labels with esc()."""
    marker = "_providerChart = new Chart"
    idx = html.find(marker)
    assert idx >= 0, "renderProviderBreakdown chart block not found"
    window = html[idx:idx + 800]
    chk("FC.XSS.03 provider breakdown labels call esc()",
        "labels: provs.map(function(p) { return esc(" in window,
        f"provider labels not escaped. window:\n{window[:400]}")


def test_fc_xss_04_optimization_trend_labels_escaped(html):
    """FC.XSS.04 — optimization trend chart wraps month labels with esc()."""
    marker = "_optTrendChart = new Chart"
    idx = html.find(marker)
    assert idx >= 0, "_optTrendChart block not found"
    window = html[idx:idx + 800]
    chk("FC.XSS.04 optimization trend labels call esc()",
        "labels: trend.map(function(r) { return esc(r.month); })" in window,
        f"optimization trend labels not escaped. window:\n{window[:400]}")


def test_fc_xss_05_no_unescaped_label_mappers(html):
    """FC.XSS.05 — no plain `labels: X.map(...)` that returns a raw string field.

    This is a broad regression net: it forbids the exact pattern we regressed
    on, so a future refactor can't silently reintroduce it. Matches:
      labels: <ident>.map(function(<ident>) { return <ident>.<field>; })
    and similar shapes that don't wrap the return value with esc(.
    """
    import re

    # Any `return X.field;` OR `return X;` inside a labels-mapper — both bad.
    # Allow `return esc(...)` and `return fmtXxx(...)` style wrappers.
    bad = re.compile(
        r"labels:\s*\w+\.map\(function\(\w+\)\s*\{\s*return\s+(?!esc\()[^;}]+;\s*\}\)",
        re.MULTILINE,
    )
    matches = bad.findall(html)
    # Known-safe exception: labels built from numeric/formatted helpers like
    # fmtXxx(), Number(...), String(n) still go through Chart.js but don't
    # carry attacker content. We still flag them so the author has to confirm.
    # Strip matches that only call a function (no property access).
    unsafe = [m for m in matches if re.search(r"\.\w+\s*[;}]", m)]
    chk(
        "FC.XSS.05 no raw-field label mappers (all wrapped in esc() or a formatter)",
        len(unsafe) == 0,
        f"unsafe label mappers found ({len(unsafe)}):\n  " + "\n  ".join(unsafe[:5]),
    )


if __name__ == "__main__":
    info("Running FC.XSS chart-label XSS regression tests")
    pytest.main([__file__, "-v"])
