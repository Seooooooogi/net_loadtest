"""Pure-math checks for the metering path. No ROS needed: pytest test/ -q
or: python3 test/test_rates.py"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from net_loadtest.rates import bps, classify, counter_rate, loss_bps, loss_pct, rate_hz


def test_counter_rate_basic():
    assert counter_rate(100, 1100, 1.0) == 1000.0
    assert counter_rate(0, 500, 2.0) == 250.0


def test_counter_rate_guards():
    assert counter_rate(100, 50, 1.0) is None      # wrap/reset -> gap, not negative
    assert counter_rate(100, 200, 0.0) is None      # bad interval
    assert counter_rate(100, 200, -1.0) is None


def test_bps_is_bytes_times_eight():
    # 1000 bytes/s -> 8000 bits/s
    assert bps(0, 1000, 1.0) == 8000.0
    assert bps(0, 50, 0) is None


def test_loss():
    assert loss_bps(1000.0, 800.0) == 200.0
    assert loss_bps(800.0, 1000.0) == 0.0            # clamp, never negative
    assert loss_pct(1000.0, 800.0) == 20.0
    assert loss_pct(0.0, 0.0) == 0.0                 # no divide-by-zero


def test_rate_hz():
    # 8 Mbps with 1000-byte payload -> 1000 msgs/s
    assert rate_hz(8.0, 1000) == 1000.0
    assert rate_hz(0.0, 1000) == 0.0                 # idle
    assert rate_hz(50.0, 0) == 0.0                    # no divide-by-zero


def test_classify():
    assert classify(0.0, 1.0, 5.0) == "good"
    assert classify(2.0, 1.0, 5.0) == "warning"
    assert classify(9.0, 1.0, 5.0) == "critical"
    assert classify(5.0, 1.0, 5.0) == "critical"     # crit is inclusive
    assert classify(None, 1.0, 5.0) == "good"        # no data


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print("ok", fn.__name__)
    print("all {} passed".format(len(fns)))
