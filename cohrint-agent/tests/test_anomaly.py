"""Tests for anomaly.py — cost anomaly detection."""
import pytest
from vantage_agent.anomaly import check_cost_anomaly


class TestCheckCostAnomaly:
    def test_no_anomaly_with_few_priors(self):
        assert check_cost_anomaly(0.10, 0.05, 1) is False

    def test_no_anomaly_zero_prior(self):
        assert check_cost_anomaly(0.10, 0.0, 5) is False

    def test_no_anomaly_normal_cost(self):
        # avg = 0.10/5 = 0.02, current 0.03 < 0.06 (3x)
        assert check_cost_anomaly(0.03, 0.10, 5) is False

    def test_anomaly_detected(self):
        # avg = 0.10/5 = 0.02, current 0.10 > 0.06 (3x)
        assert check_cost_anomaly(0.10, 0.10, 5) is True

    def test_no_anomaly_below_min_avg(self):
        # avg = 0.001/5 = 0.0002 < MIN_AVG_COST
        assert check_cost_anomaly(0.01, 0.001, 5) is False

    def test_exactly_3x_not_anomaly(self):
        # avg = 0.10/5 = 0.02, current 0.06 == 3x (not >)
        assert check_cost_anomaly(0.06, 0.10, 5) is False

    def test_just_over_3x_is_anomaly(self):
        # avg = 0.10/5 = 0.02, current 0.0601 > 0.06
        assert check_cost_anomaly(0.0601, 0.10, 5) is True
