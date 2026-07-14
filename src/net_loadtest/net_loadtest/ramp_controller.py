"""Broadcast a staged load schedule to every load_gen source.

Steps come from a YAML/param list; each step holds target_mbps + payload_bytes
for hold_sec, then advances. Published latched (transient_local) so a source that
joins late still gets the current step. The schedule is the ONLY place the ramp
lives -- load_gen just obeys.
"""
import json

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, DurabilityPolicy, HistoryPolicy
from std_msgs.msg import String

from net_loadtest import runner


class RampController(Node):
    def __init__(self):
        super().__init__("ramp_controller")
        # per-step offered load PER SOURCE, in Mbps; and payload size in bytes
        self.steps_mbps = list(self.declare_parameter(
            "steps_mbps", [10.0, 25.0, 50.0, 100.0, 200.0, 400.0]).value)
        self.payload_bytes = int(self.declare_parameter("payload_bytes", 4096).value)
        self.hold_sec = float(self.declare_parameter("hold_sec", 20.0).value)
        # loop=true -> 마지막 스텝 뒤 처음(step 0)으로 되돌아 무한 반복(Ctrl-C 로 종료).
        # shutdown_when_done=true -> 마지막 스텝 후 shutdown 플래그를 실어 전 노드(소스/sink/
        #   nic_reporter/aggregator/web/ext)를 자동 종료. grace_sec 동안 reliable 전달 보장 후 자신도 종료.
        # 둘 다 false(기본) -> idle(target 0) 한 번 publish 하고 타이머 정지.
        self.loop = bool(self.declare_parameter("loop", False).value)
        self.shutdown_when_done = bool(
            self.declare_parameter("shutdown_when_done", False).value)
        self.grace_sec = float(self.declare_parameter("grace_sec", 3.0).value)

        latched = QoSProfile(depth=1, history=HistoryPolicy.KEEP_LAST)
        latched.durability = DurabilityPolicy.TRANSIENT_LOCAL
        self.pub = self.create_publisher(String, "/loadtest/step", latched)

        self.i = -1
        self.cycle = 0
        self._timer = None
        self._advance()
        self._timer = self.create_timer(self.hold_sec, self._advance)

    def _publish(self, step_index, target_mbps, done=False, shutdown=False):
        self.pub.publish(String(data=json.dumps({
            "step_index": step_index,
            "target_mbps": target_mbps,
            "payload_bytes": self.payload_bytes,
            "hold_sec": self.hold_sec,
            "total_steps": len(self.steps_mbps),
            "done": done,
            "shutdown": shutdown,
        })))

    def _final(self):
        self._grace.cancel()
        self._stop = True

    def _advance(self):
        self.i += 1
        if self.i >= len(self.steps_mbps):
            if self.loop:
                self.cycle += 1
                self.i = 0
                self.get_logger().info("ramp loop -> cycle {}".format(self.cycle + 1))
            elif self.shutdown_when_done:
                self._publish(self.i, 0.0, done=True, shutdown=True)
                self.get_logger().info(
                    "ramp complete -> shutting down the fleet (grace {:.0f}s)".format(
                        self.grace_sec))
                if self._timer is not None:
                    self._timer.cancel()
                self._grace = self.create_timer(self.grace_sec, self._final)
                return
            else:
                self._publish(self.i, 0.0, done=True)
                self.get_logger().info("ramp complete -> sources idle")
                if self._timer is not None:
                    self._timer.cancel()   # stop re-publishing idle every hold_sec
                return
        mbps = float(self.steps_mbps[self.i])
        self._publish(self.i, mbps)
        self.get_logger().info(
            "cycle {} step {}/{}: {:.0f} Mbps/source, {}B payload, hold {:.0f}s".format(
                self.cycle + 1, self.i + 1, len(self.steps_mbps), mbps,
                self.payload_bytes, self.hold_sec))


def main():
    rclpy.init()
    runner.spin(RampController())


if __name__ == "__main__":
    main()
