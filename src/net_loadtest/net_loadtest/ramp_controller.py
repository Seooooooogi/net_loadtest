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


class RampController(Node):
    def __init__(self):
        super().__init__("ramp_controller")
        # per-step offered load PER SOURCE, in Mbps; and payload size in bytes
        self.steps_mbps = list(self.declare_parameter(
            "steps_mbps", [10.0, 25.0, 50.0, 100.0, 200.0, 400.0]).value)
        self.payload_bytes = int(self.declare_parameter("payload_bytes", 4096).value)
        self.hold_sec = float(self.declare_parameter("hold_sec", 20.0).value)

        latched = QoSProfile(depth=1, history=HistoryPolicy.KEEP_LAST)
        latched.durability = DurabilityPolicy.TRANSIENT_LOCAL
        self.pub = self.create_publisher(String, "/loadtest/step", latched)

        self.i = -1
        self._advance()
        self.create_timer(self.hold_sec, self._advance)

    def _publish(self, step_index, target_mbps, done=False):
        self.pub.publish(String(data=json.dumps({
            "step_index": step_index,
            "target_mbps": target_mbps,
            "payload_bytes": self.payload_bytes,
            "hold_sec": self.hold_sec,
            "total_steps": len(self.steps_mbps),
            "done": done,
        })))

    def _advance(self):
        self.i += 1
        if self.i >= len(self.steps_mbps):
            self._publish(self.i, 0.0, done=True)
            self.get_logger().info("ramp complete -> sources idle")
            return
        mbps = float(self.steps_mbps[self.i])
        self._publish(self.i, mbps)
        self.get_logger().info(
            "step {}/{}: {:.0f} Mbps/source, {}B payload, hold {:.0f}s".format(
                self.i + 1, len(self.steps_mbps), mbps,
                self.payload_bytes, self.hold_sec))


def main():
    rclpy.init()
    node = RampController()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
