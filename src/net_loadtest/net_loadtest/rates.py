"""Pure rate math for NIC counters. No rclpy import so it stays unit-testable."""


def counter_rate(prev, curr, elapsed):
    """Per-second rate of a monotonic counter (bytes or packets).

    Returns None on a bad interval or a counter wrap/reset (delta < 0), so the
    caller reports a gap instead of a bogus negative spike.
    """
    if elapsed <= 0:
        return None
    delta = curr - prev
    if delta < 0:  # 64-bit /sys counters rarely wrap, but reset/iface-flap can
        return None
    return delta / elapsed


def bps(prev_bytes, curr_bytes, elapsed):
    """Wire bits per second from a byte counter delta."""
    r = counter_rate(prev_bytes, curr_bytes, elapsed)
    return None if r is None else r * 8.0


def loss_bps(ingress_bps, egress_bps):
    """Bytes entering the switch minus bytes leaving = drop rate. Clamped >= 0.

    ingress = sum of every monitored port's tx_bps (traffic pushed into switch).
    egress  = sum of every monitored port's rx_bps (traffic the switch delivered).
    A positive gap means the switch/receiver is dropping. Only meaningful when
    EVERY active port runs nic_reporter; an unmonitored port undercounts egress.
    """
    return max(0.0, ingress_bps - egress_bps)


def loss_pct(ingress_bps, egress_bps):
    if ingress_bps <= 0:
        return 0.0
    return 100.0 * loss_bps(ingress_bps, egress_bps) / ingress_bps


def rate_hz(target_mbps, payload_bytes):
    """Messages/sec needed to offer target_mbps with this payload. 0 -> idle."""
    if target_mbps <= 0 or payload_bytes <= 0:
        return 0.0
    return (target_mbps * 1e6) / (payload_bytes * 8.0)


def classify(value, warn, crit):
    """Status bucket for a metric where higher = worse -> good|warning|critical.

    Used by the web dashboard to color loss/latency tiles. None -> good (no data).
    """
    if value is None:
        return "good"
    if value >= crit:
        return "critical"
    if value >= warn:
        return "warning"
    return "good"
