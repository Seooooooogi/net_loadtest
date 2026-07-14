"""Per-packet latency helpers. Pure (no rclpy) so it stays unit-testable.

Payload layout:  "<src>|<seq>|<send_ts>|" + 'x' filler up to payload_bytes.
sink decodes the header -> one-way latency (recv_ts - send_ts) and per-source
seq gaps (app-level loss). One-way latency needs NTP/PTP-synced clocks; the
queueing component (latency - min_seen) cancels a constant clock offset.
"""

MIN_PAYLOAD = 48  # must exceed the header so filler >= 0


def encode(src, seq, ts, payload_bytes):
    header = "{}|{}|{:.6f}|".format(src, seq, ts)
    pad = payload_bytes - len(header)
    return header + ("x" * pad if pad > 0 else "")


def decode(data):
    """-> (src, seq, ts) or None if it isn't one of our packets."""
    parts = data.split("|", 3)
    if len(parts) < 4:
        return None
    try:
        return parts[0], int(parts[1]), float(parts[2])
    except ValueError:
        return None


def percentile(sorted_vals, q):
    """Nearest-rank percentile of a PRE-SORTED list. q in [0,100]. None if empty."""
    if not sorted_vals:
        return None
    k = int(round((q / 100.0) * (len(sorted_vals) - 1)))
    return sorted_vals[k]


def latency_stats(samples_ms):
    """min/p50/p95/max/mean over a window of latency samples (ms)."""
    if not samples_ms:
        return None
    s = sorted(samples_ms)
    return {
        "count": len(s),
        "min_ms": round(s[0], 3),
        "p50_ms": round(percentile(s, 50), 3),
        "p95_ms": round(percentile(s, 95), 3),
        "max_ms": round(s[-1], 3),
        "mean_ms": round(sum(s) / len(s), 3),
    }
