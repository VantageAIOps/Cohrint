"""Central config — all values from environment variables. No defaults that touch production secrets."""
import os
from pathlib import Path

TESTS_ROOT = Path(__file__).parent.parent

SITE_URL = os.environ.get("VANTAGE_SITE_URL", "https://cohrint.com")
API_URL  = os.environ.get("VANTAGE_API_URL",  "https://api.cohrint.com")
HEADLESS = os.environ.get("HEADLESS", "1") != "0"

ARTIFACTS_DIR = Path(os.environ.get("VANTAGE_TEST_ARTIFACTS_DIR", str(TESTS_ROOT / "artifacts")))
ARTIFACT_MAX_AGE_DAYS = int(os.environ.get("VANTAGE_ARTIFACT_MAX_AGE_DAYS", "7"))
LOG_LEVEL = os.environ.get("VANTAGE_LOG_LEVEL", "INFO")

# Pre-seeded CI test account — avoids signup rate limits in CI
# Set these as GitHub Secrets to skip fresh_account() signups
CI_API_KEY = os.environ.get("VANTAGE_CI_API_KEY", "")
CI_ORG_ID  = os.environ.get("VANTAGE_CI_ORG_ID", "")

# Integration secrets — tests SKIP if these are not set
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")
TEAMS_WEBHOOK_URL = os.environ.get("TEAMS_WEBHOOK_URL", "")
ALERT_EMAIL       = os.environ.get("VANTAGE_ALERT_EMAIL", "")

# CI bypass secret — skips signup rate limiting when header matches
CI_SECRET  = os.environ.get("VANTAGE_CI_SECRET", "")
