"""Shared fleet-shutdown handling. ramp_controller sets shutdown=true on the
final /loadtest/step; every node that sees it stops, so a one-shot run cleans up
across all hosts without manual Ctrl-C.

We use a flag + spin_once loop rather than calling rclpy.shutdown() inside a
callback -- the latter does not reliably wake rclpy.spin() on Humble.
"""
import rclpy


def on_shutdown_flag(node, step_dict):
    """True (and flags this node to stop) if a step msg carries shutdown."""
    if step_dict.get("shutdown"):
        node.get_logger().info("shutdown signal received -> exiting")
        node._stop = True
        return True
    return False


def spin(node):
    """Spin until Ctrl-C or node._stop (set by the fleet-shutdown flag)."""
    node._stop = False
    try:
        while rclpy.ok() and not node._stop:
            rclpy.spin_once(node, timeout_sec=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()
