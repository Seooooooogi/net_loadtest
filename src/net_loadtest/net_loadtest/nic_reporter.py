"""Poll /sys/class/net/<iface>/statistics and publish per-port wire rates.

One reporter per host. host 1 = switch port 1, so its NIC tx/rx bytes ARE the
per-port wire load (headers + RTPS overhead included, unlike app-level goodput).
Publishes std_msgs/String JSON on /loadtest/nic; the aggregator sums them.
"""
import json
import socket
import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from net_loadtest.rates import bps, counter_rate
from net_loadtest.runner import on_shutdown_flag, spin as run_spin

_FIELDS = ("rx_bytes", "tx_bytes", "rx_packets", "tx_packets",
           "rx_dropped", "tx_dropped")


def read_counters(iface):
    """Read the raw counters for one iface. Missing iface -> FileNotFoundError."""
    base = "/sys/class/net/{}/statistics/".format(iface)
    out = {}
    for f in _FIELDS:
        with open(base + f) as fh:
            out[f] = int(fh.read())
    return out


class NicReporter(Node):
    def __init__(self):
        super().__init__("nic_reporter")
        self.iface = self.declare_parameter("iface", "").value
        self.interval = float(self.declare_parameter("interval_sec", 1.0).value)
        self.host = self.declare_parameter("host", socket.gethostname()).value
        if not self.iface:
            raise SystemExit(
                "nic_reporter: -p iface:=<name> required "
                "(e.g. enp11s0). Refusing to guess the wrong port.")
        # fail loud now rather than silently measure nothing
        read_counters(self.iface)

        self.step = -1
        self.pub = self.create_publisher(String, "/loadtest/nic", 10)
        self.create_subscription(String, "/loadtest/step", self._on_step, 10)
        self._prev = read_counters(self.iface)
        self._prev_t = time.monotonic()
        self.create_timer(self.interval, self._tick)
        self.get_logger().info(
            "reporting {} on iface {} every {:.1f}s".format(
                self.host, self.iface, self.interval))

    def _on_step(self, msg):
        try:
            d = json.loads(msg.data)
        except ValueError:
            return
        if on_shutdown_flag(self, d):
            return
        self.step = int(d.get("step_index", -1))

    def _tick(self):
        now = time.monotonic()
        elapsed = now - self._prev_t
        try:
            curr = read_counters(self.iface)
        except FileNotFoundError:
            self.get_logger().warn("iface {} vanished".format(self.iface))
            return
        row = {
            "host": self.host, "iface": self.iface, "step": self.step,
            "ts": time.time(),
            "rx_bps": bps(self._prev["rx_bytes"], curr["rx_bytes"], elapsed),
            "tx_bps": bps(self._prev["tx_bytes"], curr["tx_bytes"], elapsed),
            "rx_pps": counter_rate(self._prev["rx_packets"], curr["rx_packets"], elapsed),
            "tx_pps": counter_rate(self._prev["tx_packets"], curr["tx_packets"], elapsed),
            "rx_drop": curr["rx_dropped"] - self._prev["rx_dropped"],
            "tx_drop": curr["tx_dropped"] - self._prev["tx_dropped"],
        }
        self._prev, self._prev_t = curr, now
        self.pub.publish(String(data=json.dumps(row)))


def main():
    rclpy.init()
    run_spin(NicReporter())


if __name__ == "__main__":
    main()
