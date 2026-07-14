"""External-generator adapter: drive performance_test (or ANY generator) from the
same ramp, measured by the same nic_reporter/aggregator meter.

Why a template instead of hardcoded perf_test flags: perf_test's CLI differs
across versions (--communication/--msg vs -c/-m ...). We refuse to bake flags we
can't verify. You supply `source_cmd` with placeholders; we fill and run it once
per ramp step for that step's duration. Empty -> the adapter idles and tells you
how to set it. perf_test traffic has no seq header, so the sink counts it as
'foreign' and latency comes from perf_test's own report; our stack gives the
switch-level bps/loss.

Placeholders: {rate} msgs/s, {mbps} per-source Mbps, {payload} bytes, {seconds} hold.

perf_test example (VERIFY flags against your `perf_test --help`):
  source_cmd:="perf_test -c ROS2 -m Array4k --rate {rate} --max-runtime {seconds} -p 1 -s 0"
iperf3 example (needs `iperf3 -s` on the sink, sink_ip in the template):
  source_cmd:="iperf3 -c 10.0.0.9 -u -b {mbps}M -t {seconds}"
"""
import json
import shlex
import shutil
import subprocess

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, DurabilityPolicy, HistoryPolicy
from std_msgs.msg import String

from net_loadtest.rates import rate_hz


class ExtSource(Node):
    def __init__(self):
        super().__init__("ext_source")
        self.cmd = self.declare_parameter("source_cmd", "").value
        self.proc = None
        if not self.cmd:
            self.get_logger().warn(
                "source_cmd empty -> idle. Set e.g. "
                "-p source_cmd:='perf_test -c ROS2 -m Array4k --rate {rate} "
                "--max-runtime {seconds} -p 1 -s 0' (verify flags for your version)")
        else:
            binary = shlex.split(self.cmd)[0]
            if shutil.which(binary) is None:
                self.get_logger().warn(
                    "'{}' not on PATH -- install it or fix source_cmd; steps will "
                    "be skipped until then".format(binary))
        latched = QoSProfile(depth=1, history=HistoryPolicy.KEEP_LAST)
        latched.durability = DurabilityPolicy.TRANSIENT_LOCAL
        self.create_subscription(String, "/loadtest/step", self._on_step, latched)

    def _kill(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None

    def _on_step(self, msg):
        try:
            d = json.loads(msg.data)
        except ValueError:
            return
        self._kill()
        target = float(d.get("target_mbps", 0.0))
        if target <= 0 or not self.cmd:
            return
        payload = int(d.get("payload_bytes", 4096))
        seconds = float(d.get("hold_sec", 20.0))
        hz = rate_hz(target, payload)
        cmd = self.cmd.format(rate=int(hz), mbps=target, payload=payload,
                              seconds=int(seconds))
        try:
            self.proc = subprocess.Popen(shlex.split(cmd))
            self.get_logger().info("step {} -> {}".format(
                d.get("step_index"), cmd))
        except (OSError, ValueError) as e:
            self.get_logger().error("failed to run '{}': {}".format(cmd, e))

    def destroy_node(self):
        try:
            self._kill()
        finally:
            super().destroy_node()


def main():
    rclpy.init()
    node = ExtSource()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
