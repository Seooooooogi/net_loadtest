"""Traffic source/sink. Sources publish a fixed-size payload at a rate driven by
the ramp_controller; the sink receives, and (from our header) measures one-way
latency + per-source seq-gap loss.

Topology default = many-to-one: every source publishes to the same topic, one
sink subscribes. On a non-blocking switch that convergence onto one 2.5G port is
what actually reveals the ceiling (port saturation + 8 Mbit buffer drops).

Payload = std_msgs/String: "<src>|<seq>|<send_ts>|" + 'x' filler. Cheapest way to
carry seq+timestamp AND a controllable size without a custom .msg / rosidl build.
"""
import json
import socket
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy, HistoryPolicy
from std_msgs.msg import String

from net_loadtest import packet
from net_loadtest.rates import rate_hz
from net_loadtest.runner import on_shutdown_flag, spin as run_spin


class LoadGen(Node):
    def __init__(self):
        super().__init__("load_gen")
        self.mode = self.declare_parameter("mode", "source").value  # source|sink
        self.topic = self.declare_parameter("topic", "/loadtest/traffic").value
        self.payload_bytes = int(self.declare_parameter("payload_bytes", 1024).value)
        self.target_mbps = float(self.declare_parameter("target_mbps", 0.0).value)
        # ponytail: timer-driven publish caps out at a few kHz; to offer more
        # throughput raise payload_bytes, not rate. max_rate_hz guards CPU meltdown.
        self.max_rate_hz = float(self.declare_parameter("max_rate_hz", 5000.0).value)
        self.report_sec = float(self.declare_parameter("report_sec", 1.0).value)
        # ponytail: bound the per-window sample list so a multi-kHz sink can't OOM
        self.sample_cap = int(self.declare_parameter("sample_cap", 20000).value)
        reliable = self.declare_parameter("reliable", False).value
        self.src = socket.gethostname().split(".")[0]
        self.step = -1

        qos = QoSProfile(depth=10, history=HistoryPolicy.KEEP_LAST)
        qos.reliability = (ReliabilityPolicy.RELIABLE if reliable
                           else ReliabilityPolicy.BEST_EFFORT)

        self.create_subscription(String, "/loadtest/step", self._on_step, self._latched())

        if self.mode == "sink":
            self._init_sink(qos)
        else:
            self._init_source(qos)

    # ---- shared ----
    def _latched(self):
        q = QoSProfile(depth=1, history=HistoryPolicy.KEEP_LAST)
        q.durability = DurabilityPolicy.TRANSIENT_LOCAL
        return q

    def _on_step(self, msg):
        try:
            d = json.loads(msg.data)
        except ValueError:
            return
        if on_shutdown_flag(self, d):
            return
        self.step = int(d.get("step_index", self.step))
        if self.mode == "source":
            self.target_mbps = float(d.get("target_mbps", self.target_mbps))
            self.payload_bytes = int(d.get("payload_bytes", self.payload_bytes))
            self._apply()

    # ---- source ----
    def _init_source(self, qos):
        self.pub = self.create_publisher(String, self.topic, qos)
        self.seq = 0
        self._timer = None
        self._apply()

    def _apply(self):
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        if self.payload_bytes < packet.MIN_PAYLOAD:
            self.get_logger().warn("payload_bytes {} < min {}; bumping".format(
                self.payload_bytes, packet.MIN_PAYLOAD))
            self.payload_bytes = packet.MIN_PAYLOAD
        hz = rate_hz(self.target_mbps, self.payload_bytes)
        if hz <= 0:
            self.get_logger().info("idle (target 0)")
            return
        if hz > self.max_rate_hz:
            self.get_logger().warn(
                "want {:.0f} Hz > cap {:.0f}; capping (raise payload_bytes for "
                "more throughput)".format(hz, self.max_rate_hz))
            hz = self.max_rate_hz
        self._timer = self.create_timer(1.0 / hz, self._pub_once)
        self.get_logger().info("source {:.0f}B @ {:.0f}Hz -> ~{:.1f} Mbps".format(
            self.payload_bytes, hz, hz * self.payload_bytes * 8 / 1e6))

    def _pub_once(self):
        self.pub.publish(String(data=packet.encode(
            self.src, self.seq, time.time(), self.payload_bytes)))
        self.seq += 1

    # ---- sink ----
    def _init_sink(self, qos):
        self.recv = 0
        self.foreign = 0          # packets without our header (e.g. perf_test traffic)
        self.gap_loss = 0
        self.last_seq = {}        # src -> last seq seen
        self.samples = []         # latency ms, current window
        self.min_ms = None        # all-time min -> queueing delay baseline
        self.create_subscription(String, self.topic, self._on_msg, qos)
        self.pub = self.create_publisher(String, "/loadtest/latency", 10)
        self.create_timer(self.report_sec, self._report)
        self.get_logger().info("sink on {} (measuring latency + seq gaps)".format(self.topic))

    def _on_msg(self, msg):
        self.recv += 1
        now = time.time()
        dec = packet.decode(msg.data)
        if dec is None:
            self.foreign += 1
            return
        src, seq, ts = dec
        lat_ms = (now - ts) * 1000.0
        if len(self.samples) < self.sample_cap:
            self.samples.append(lat_ms)
        if self.min_ms is None or lat_ms < self.min_ms:
            self.min_ms = lat_ms
        prev = self.last_seq.get(src)
        if prev is not None and seq > prev + 1:
            self.gap_loss += seq - prev - 1
        self.last_seq[src] = seq

    def _report(self):
        stats = packet.latency_stats(self.samples)
        self.samples = []
        out = {"host": self.src, "step": self.step, "recv": self.recv,
               "foreign": self.foreign, "gap_loss": self.gap_loss}
        if stats:
            out.update(stats)
            if self.min_ms is not None:
                out["queueing_p95_ms"] = round(stats["p95_ms"] - self.min_ms, 3)
        self.pub.publish(String(data=json.dumps(out)))
        if stats:
            self.get_logger().info(
                "lat p50 {:.2f} p95 {:.2f} max {:.2f} ms | queueing_p95 {:.2f} "
                "| gap_loss {} | foreign {}".format(
                    stats["p50_ms"], stats["p95_ms"], stats["max_ms"],
                    out.get("queueing_p95_ms", 0.0), self.gap_loss, self.foreign))


def main():
    rclpy.init()
    run_spin(LoadGen())


if __name__ == "__main__":
    main()
