"""Collect every nic_reporter + sink-latency feed, sum to switch-level totals, log.

  per-port bps      = each reporter's rx_bps / tx_bps
  switch ingress    = Sum(tx_bps) over all ports  (bytes pushed into switch)
  switch egress     = Sum(rx_bps) over all ports  (bytes switch delivered)
  loss              = ingress - egress             (>0 => switch/receiver dropping)
  latency           = sink one-way p50/p95/max; queueing = p95 - min (offset-free)

The switch's "capacity" is the offered load where loss/queueing first climbs off
zero -- not peak bps. Two CSVs (run-scoped, append-only, never overwritten):
  loadtest_<ts>.csv          per-port detail rows
  loadtest_<ts>_summary.csv  switch aggregate + latency, one row/sec
"""
import csv
import json
import os
import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from net_loadtest.rates import loss_bps, loss_pct

_PORT_COLS = ["ts", "step", "target_mbps", "host", "iface",
              "rx_bps", "tx_bps", "rx_pps", "tx_pps", "rx_drop", "tx_drop"]
_SUM_COLS = ["ts", "step", "target_mbps", "ports",
             "switch_ingress_mbps", "switch_egress_mbps", "loss_mbps", "loss_pct",
             "max_port_mbps", "nic_rx_drops",
             "lat_p50_ms", "lat_p95_ms", "lat_max_ms", "queueing_p95_ms", "gap_loss"]


class Aggregator(Node):
    def __init__(self):
        super().__init__("aggregator")
        out_dir = os.path.expanduser(
            self.declare_parameter("out_dir", "~/loadtest_runs").value)
        os.makedirs(out_dir, exist_ok=True)
        run = time.strftime("%Y%m%d_%H%M%S")
        self._csv, self._w = self._open(out_dir, "loadtest_{}.csv".format(run), _PORT_COLS)
        self._scsv, self._sw = self._open(
            out_dir, "loadtest_{}_summary.csv".format(run), _SUM_COLS)

        self.step = -1
        self.target_mbps = 0.0
        self.latest = {}   # (host, iface) -> nic row
        self.latency = {}  # sink host -> latency row
        self.create_subscription(String, "/loadtest/nic", self._on_nic, 50)
        self.create_subscription(String, "/loadtest/latency", self._on_lat, 10)
        self.create_subscription(String, "/loadtest/step", self._on_step, 10)
        self.pub = self.create_publisher(String, "/loadtest/summary", 10)
        self.create_timer(1.0, self._report)
        self.get_logger().info("logging detail+summary under {}".format(out_dir))

    @staticmethod
    def _open(out_dir, name, cols):
        fh = open(os.path.join(out_dir, name), "w", newline="")
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        return fh, w

    def _on_step(self, msg):
        try:
            d = json.loads(msg.data)
            self.step = int(d.get("step_index", -1))
            self.target_mbps = float(d.get("target_mbps", 0.0))
        except (ValueError, KeyError):
            pass

    def _on_nic(self, msg):
        try:
            row = json.loads(msg.data)
        except ValueError:
            return
        row["target_mbps"] = self.target_mbps
        if row.get("step", -1) < 0:
            row["step"] = self.step
        self.latest[(row.get("host"), row.get("iface"))] = row
        self._w.writerow(row)
        self._csv.flush()

    def _on_lat(self, msg):
        try:
            self.latency[json.loads(msg.data).get("host")] = json.loads(msg.data)
        except ValueError:
            pass

    def _report(self):
        if not self.latest:
            return
        ingress = sum((r.get("tx_bps") or 0.0) for r in self.latest.values())
        egress = sum((r.get("rx_bps") or 0.0) for r in self.latest.values())
        max_port = max(max(r.get("rx_bps") or 0.0, r.get("tx_bps") or 0.0)
                       for r in self.latest.values())
        drops = sum(int(r.get("rx_drop") or 0) for r in self.latest.values())
        # merge latency across sinks (worst p95, summed gap loss)
        lats = list(self.latency.values())
        p50 = max((l.get("p50_ms", 0.0) for l in lats), default=0.0)
        p95 = max((l.get("p95_ms", 0.0) for l in lats), default=0.0)
        mx = max((l.get("max_ms", 0.0) for l in lats), default=0.0)
        q95 = max((l.get("queueing_p95_ms", 0.0) for l in lats), default=0.0)
        gap = sum(int(l.get("gap_loss", 0)) for l in lats)

        row = {
            "ts": time.time(), "step": self.step, "target_mbps": self.target_mbps,
            "ports": len(self.latest),
            "switch_ingress_mbps": round(ingress / 1e6, 2),
            "switch_egress_mbps": round(egress / 1e6, 2),
            "loss_mbps": round(loss_bps(ingress, egress) / 1e6, 2),
            "loss_pct": round(loss_pct(ingress, egress), 2),
            "max_port_mbps": round(max_port / 1e6, 2),
            "nic_rx_drops": drops,
            "lat_p50_ms": p50, "lat_p95_ms": p95, "lat_max_ms": mx,
            "queueing_p95_ms": q95, "gap_loss": gap,
        }
        self._sw.writerow(row)
        self._scsv.flush()
        self.pub.publish(String(data=json.dumps(row)))
        self.get_logger().info(
            "step {} target {:.0f} | in {:.1f} out {:.1f} Mbps loss {:.1f}% "
            "| maxport {:.1f} | lat p95 {:.2f} q95 {:.2f} ms | gaploss {} drops {}".format(
                self.step, self.target_mbps, row["switch_ingress_mbps"],
                row["switch_egress_mbps"], row["loss_pct"], row["max_port_mbps"],
                p95, q95, gap, drops))

    def destroy_node(self):
        try:
            self._csv.close()
            self._scsv.close()
        finally:
            super().destroy_node()


def main():
    rclpy.init()
    node = Aggregator()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
