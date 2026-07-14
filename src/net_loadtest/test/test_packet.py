"""Per-packet latency helpers. ROS-free: pytest test/ -q  or  python3 test/test_packet.py"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from net_loadtest.packet import (MIN_PAYLOAD, decode, encode, latency_stats,
                                 percentile)


def test_roundtrip():
    data = encode("hostA", 42, 1234.5, 256)
    assert decode(data) == ("hostA", 42, 1234.5)


def test_size_exact_when_big_enough():
    assert len(encode("h", 1, 0.0, 200)) == 200


def test_size_floor_when_too_small():
    # header longer than requested size -> send header only, never truncate it
    data = encode("longhostname", 999999, 1699999999.123456, 4)
    assert decode(data) == ("longhostname", 999999, 1699999999.123456)


def test_decode_rejects_foreign():
    assert decode("xxxxxxxxxxxx") is None          # perf_test / non-header traffic
    assert decode("h|notanint|1.0|pad") is None


def test_percentile():
    s = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    assert percentile(s, 0) == 1
    assert percentile(s, 100) == 10
    assert percentile(s, 50) in (5, 6)
    assert percentile([], 50) is None


def test_latency_stats():
    st = latency_stats([10.0, 20.0, 30.0, 40.0])
    assert st["count"] == 4
    assert st["min_ms"] == 10.0
    assert st["max_ms"] == 40.0
    assert st["mean_ms"] == 25.0
    assert latency_stats([]) is None


def test_min_payload_sane():
    assert MIN_PAYLOAD >= len("|".join(["h", "0", "0.000000"])) + 1


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print("ok", fn.__name__)
    print("all {} passed".format(len(fns)))
