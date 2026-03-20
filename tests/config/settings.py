"""Central config — all values from environment variables. No defaults that touch production secrets."""
import os
from pathlib import Path

TESTS_ROOT = Path(__file__).parent.parent

SITE_URL = os.environ.get("VANTAGE_SITE_URL", "https://vantageaiops.com")
API_URL  = os.environ.get("VANTAGE_API_URL",  "https://api.vantageaiops.com")
HEADLESS = os.environ.get("HEADLESS", "1") != "0"

ARTIFACTS_DIR = Path(os.environ.get("VANTAGE_TEST_ARTIFACTS_DIR", str(TESTS_ROOT / "artifacts")))
ARTIFACT_MAX_AGE_DAYS = int(os.environ.get("VANTAGE_ARTIFACT_MAX_AGE_DAYS", "7"))
LOG_LEVEL = os.environ.get("VANTAGE_LOG_LEVEL", "INFO")

# Integration secrets — tests SKIP if these are not set
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")
TEAMS_WEBHOOK_URL = os.environ.get("TEAMS_WEBHOOK_URL", "")
ALERT_EMAIL       = os.environ.get("VANTAGE_ALERT_EMAIL", "")
