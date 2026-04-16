"""
Test Suite 22 — Cohrint Landing Page
Verifies the landing page content reflects all v2 features.
Reads index.html from local file (not deployed site) and checks HTML content.
"""
import re, sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from helpers.output import section, chk, ok, fail, get_results, reset_results

INDEX_HTML = Path(__file__).parent.parent.parent.parent / "cohrint-frontend" / "index.html"


def get_html():
    return INDEX_HTML.read_text()


# ── helpers ──────────────────────────────────────────────────────────────────

def _has(html: str, text: str) -> bool:
    """Case-insensitive substring check."""
    return text.lower() in html.lower()


def _has_id(html: str, id_val: str) -> bool:
    """Check if id="<id_val>" exists in the HTML."""
    return f'id="{id_val}"' in html


# ── Section A: Hero & Install (LP.1-LP.5) ────────────────────────────────────

class TestHeroAndInstall:
    def test_lp01_title_contains_vantageai(self):
        section("A — Hero & Install")
        html = get_html()
        cond = _has(html, "<title>") and _has(html, "vantageai")
        chk("LP.1 page title contains Cohrint", cond)
        assert cond

    def test_lp02_hero_pip_install(self):
        html = get_html()
        cond = _has(html, "pip install cohrint")
        chk("LP.2 hero has 'pip install cohrint'", cond)
        assert cond

    def test_lp03_hero_npm_install(self):
        html = get_html()
        cond = _has(html, "npm install cohrint")
        chk("LP.3 hero has 'npm install cohrint'", cond)
        assert cond

    def test_lp04_hero_npx_cli(self):
        html = get_html()
        cond = _has(html, "npx vantageai-cli")
        chk("LP.4 hero has 'npx vantageai-cli'", cond)
        assert cond

    def test_lp05_hero_start_for_free_cta(self):
        html = get_html()
        cond = _has(html, "Start for free")
        chk("LP.5 hero has 'Start for free' CTA", cond)
        assert cond


# ── Section B: Features (LP.6-LP.14) ─────────────────────────────────────────

class TestFeatures:
    def test_lp06_cross_platform_otel_collector(self):
        section("B — Features")
        html = get_html()
        cond = _has(html, "Cross-platform OTel collector")
        chk("LP.6 has 'Cross-platform OTel collector' feature card", cond)
        assert cond

    def test_lp07_vantageai_cli(self):
        html = get_html()
        cond = _has(html, "Cohrint CLI")
        chk("LP.7 has 'Cohrint CLI' feature card", cond)
        assert cond

    def test_lp08_local_proxy(self):
        html = get_html()
        cond = _has(html, "Local proxy")
        chk("LP.8 has 'Local proxy' feature card", cond)
        assert cond

    def test_lp09_developer_productivity_roi(self):
        html = get_html()
        cond = _has(html, "Developer productivity ROI")
        chk("LP.9 has 'Developer productivity ROI' feature card", cond)
        assert cond

    def test_lp10_token_cost_analytics(self):
        html = get_html()
        cond = _has(html, "Token &amp; cost analytics") or _has(html, "Token & cost analytics")
        chk("LP.10 has 'Token & cost analytics' feature card", cond)
        assert cond

    def test_lp11_token_prompt_optimizer(self):
        html = get_html()
        cond = _has(html, "Token &amp; prompt optimizer") or _has(html, "Token & prompt optimizer")
        chk("LP.11 has 'Token & prompt optimizer' feature card", cond)
        assert cond

    def test_lp12_mcp_feature(self):
        html = get_html()
        cond = _has(html, "MCP") and _has(html, "ask your AI about costs")
        chk("LP.12 has 'MCP' feature card", cond)
        assert cond

    def test_lp13_budget_alerts(self):
        html = get_html()
        cond = _has(html, "Budget alerts")
        chk("LP.13 has 'Budget alerts' feature card", cond)
        assert cond

    def test_lp14_anomaly_detection(self):
        html = get_html()
        cond = _has(html, "Anomaly detection")
        chk("LP.14 has 'Anomaly detection' feature card", cond)
        assert cond


# ── Section C: Integrations (LP.15-LP.20) ────────────────────────────────────

class TestIntegrations:
    def test_lp15_claude_code_integration(self):
        section("C — Integrations")
        html = get_html()
        # Check in integrations grid specifically
        integrations_section = html[html.find('id="integrations"'):html.find("<!-- CODE EXAMPLES -->")]
        cond = _has(integrations_section, "Claude Code")
        chk("LP.15 has Claude Code integration", cond)
        assert cond

    def test_lp16_cursor_integration(self):
        html = get_html()
        integrations_section = html[html.find('id="integrations"'):html.find("<!-- CODE EXAMPLES -->")]
        cond = _has(integrations_section, "Cursor")
        chk("LP.16 has Cursor integration", cond)
        assert cond

    def test_lp17_windsurf_integration(self):
        html = get_html()
        integrations_section = html[html.find('id="integrations"'):html.find("<!-- CODE EXAMPLES -->")]
        cond = _has(integrations_section, "Windsurf")
        chk("LP.17 has Windsurf integration", cond)
        assert cond

    def test_lp18_vantageai_cli_integration(self):
        html = get_html()
        integrations_section = html[html.find('id="integrations"'):html.find("<!-- CODE EXAMPLES -->")]
        cond = _has(integrations_section, ">Cohrint CLI<")
        chk("LP.18 has Cohrint CLI integration card", cond)
        assert cond

    def test_lp19_otel_collector_integration(self):
        html = get_html()
        integrations_section = html[html.find('id="integrations"'):html.find("<!-- CODE EXAMPLES -->")]
        cond = _has(integrations_section, "OTel Collector")
        chk("LP.19 has OTel Collector integration card", cond)
        assert cond

    def test_lp20_local_proxy_integration(self):
        html = get_html()
        integrations_section = html[html.find('id="integrations"'):html.find("<!-- CODE EXAMPLES -->")]
        cond = _has(integrations_section, "Local Proxy")
        chk("LP.20 has Local Proxy integration card", cond)
        assert cond


# ── Section D: Code Examples (LP.21-LP.24) ───────────────────────────────────

class TestCodeExamples:
    def test_lp21_python_tab(self):
        section("D — Code Examples")
        html = get_html()
        cond = 'switchTab(\'python\'' in html or 'id="tab-python"' in html
        chk("LP.21 has Python tab", cond)
        assert cond

    def test_lp22_typescript_tab(self):
        html = get_html()
        cond = 'switchTab(\'typescript\'' in html or 'id="tab-typescript"' in html
        chk("LP.22 has TypeScript tab", cond)
        assert cond

    def test_lp23_mcp_tab(self):
        html = get_html()
        cond = 'switchTab(\'mcp\'' in html or 'id="tab-mcp"' in html
        chk("LP.23 has MCP tab", cond)
        assert cond

    def test_lp24_cli_wrapper_tab(self):
        html = get_html()
        cond = 'switchTab(\'cli\'' in html or 'id="tab-cli"' in html
        chk("LP.24 has CLI Wrapper tab", cond)
        assert cond


# ── Section E: Interactive Demo (LP.25-LP.29) ────────────────────────────────

class TestInteractiveDemo:
    def test_lp25_dp_overview_panel(self):
        section("E — Interactive Demo")
        html = get_html()
        cond = _has_id(html, "dp-overview")
        chk("LP.25 has 'dp-overview' demo panel", cond)
        assert cond

    def test_lp26_dp_cli_panel(self):
        html = get_html()
        cond = _has_id(html, "dp-cli")
        chk("LP.26 has 'dp-cli' demo panel", cond)
        assert cond

    def test_lp27_dp_optimizer_panel(self):
        html = get_html()
        cond = _has_id(html, "dp-optimizer")
        chk("LP.27 has 'dp-optimizer' demo panel", cond)
        assert cond

    def test_lp28_dp_otel_panel(self):
        html = get_html()
        cond = _has_id(html, "dp-otel")
        chk("LP.28 has 'dp-otel' demo panel", cond)
        assert cond

    def test_lp29_dp_compare_panel(self):
        html = get_html()
        cond = _has_id(html, "dp-compare")
        chk("LP.29 has 'dp-compare' demo panel", cond)
        assert cond


# ── Section F: Comparison + FAQ (LP.30-LP.35) ────────────────────────────────

class TestComparisonAndFaq:
    def test_lp30_comparison_cross_platform_otel(self):
        section("F — Comparison + FAQ")
        html = get_html()
        compare_section = html[html.find('id="compare"'):html.find("<!-- TRUST -->")]
        cond = _has(compare_section, "Cross-platform OTel")
        chk("LP.30 comparison table has 'Cross-platform OTel' row", cond)
        assert cond

    def test_lp31_comparison_cli_agent_wrapper(self):
        html = get_html()
        compare_section = html[html.find('id="compare"'):html.find("<!-- TRUST -->")]
        cond = _has(compare_section, "CLI agent wrapper")
        chk("LP.31 comparison table has 'CLI agent wrapper' row", cond)
        assert cond

    def test_lp32_comparison_privacy_first_local_proxy(self):
        html = get_html()
        compare_section = html[html.find('id="compare"'):html.find("<!-- TRUST -->")]
        cond = _has(compare_section, "Privacy-first local proxy")
        chk("LP.32 comparison table has 'Privacy-first local proxy' row", cond)
        assert cond

    def test_lp33_faq_vantageai_cli(self):
        html = get_html()
        faq_section = html[html.find('id="faq"'):]
        cond = _has(faq_section, "Cohrint CLI")
        chk("LP.33 FAQ has 'Cohrint CLI' question", cond)
        assert cond

    def test_lp34_faq_cross_platform_otel_tracking(self):
        html = get_html()
        faq_section = html[html.find('id="faq"'):]
        cond = _has(faq_section, "cross-platform OTel tracking")
        chk("LP.34 FAQ has 'cross-platform OTel tracking' question", cond)
        assert cond

    def test_lp35_no_broken_internal_links(self):
        html = get_html()
        # Find all href="#xxx" anchors
        anchor_links = re.findall(r'href="#([a-zA-Z][\w-]*)"', html)
        # Find all id="xxx" elements
        id_elements = set(re.findall(r'id="([a-zA-Z][\w-]*)"', html))
        broken = [f"#{a}" for a in anchor_links if a not in id_elements]
        cond = len(broken) == 0
        detail = f"broken anchors: {broken}" if broken else ""
        chk("LP.35 no broken internal links (all #anchors have matching id=)", cond, detail)
        assert cond, detail
