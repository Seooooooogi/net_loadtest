"""Real-time web dashboard for the load test. Subscribes /loadtest/summary +
/loadtest/nic and serves a self-contained page that live-updates over SSE
(Server-Sent Events). No browser-side ROS, no external JS/CSS -> runs fully
offline on the closed network.

  stdlib http.server (ThreadingHTTPServer) -> one thread per SSE client.
  ROS callback pushes each new summary into every client's queue.
Open http://<coordinator-ip>:<port>/  (remember: new port needs `sudo ufw allow`).
"""
import json
import threading
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from queue import Empty, Full, Queue

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from net_loadtest.rates import classify
from net_loadtest.web_ui import PAGE


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):  # silence per-request logging
        pass

    def do_GET(self):
        if self.path.split("?")[0] == "/events":
            return self._events()
        if self.path == "/" or self.path.startswith("/index"):
            body = PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    def _sse(self, data):
        self.wfile.write(b"data: " + data.encode("utf-8") + b"\n\n")
        self.wfile.flush()

    def _events(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        q = self.server.register()
        try:
            for item in self.server.backlog():   # replay so a refresh keeps the chart
                self._sse(item)
            while True:
                try:
                    self._sse(q.get(timeout=15))
                except Empty:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ValueError):
            pass
        finally:
            self.server.unregister(q)


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, addr, history):
        super().__init__(addr, _Handler)
        self._clients = set()
        self._backlog = deque(maxlen=history)
        self._lock = threading.Lock()

    def register(self):
        q = Queue(maxsize=64)
        with self._lock:
            self._clients.add(q)
        return q

    def unregister(self, q):
        with self._lock:
            self._clients.discard(q)

    def backlog(self):
        with self._lock:
            return list(self._backlog)

    def broadcast(self, data):
        with self._lock:
            self._backlog.append(data)
            clients = list(self._clients)
        for q in clients:
            try:
                q.put_nowait(data)
            except Full:
                try:                       # drop oldest, keep latest
                    q.get_nowait()
                    q.put_nowait(data)
                except (Empty, Full):
                    pass


class WebMonitor(Node):
    def __init__(self):
        super().__init__("web_monitor")
        port = int(self.declare_parameter("port", 8088).value)
        bind = self.declare_parameter("bind", "0.0.0.0").value
        history = int(self.declare_parameter("history", 300).value)
        self.loss_warn = float(self.declare_parameter("loss_warn_pct", 1.0).value)
        self.loss_crit = float(self.declare_parameter("loss_crit_pct", 5.0).value)
        self.lat_warn = float(self.declare_parameter("lat_warn_ms", 5.0).value)
        self.lat_crit = float(self.declare_parameter("lat_crit_ms", 20.0).value)

        self.nic = {}  # (host,iface) -> row
        self.create_subscription(String, "/loadtest/summary", self._on_summary, 10)
        self.create_subscription(String, "/loadtest/nic", self._on_nic, 50)

        self.server = _Server((bind, port), history)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.get_logger().info(
            "dashboard on http://{}:{}/  (open in a browser; `sudo ufw allow {}` "
            "if firewalled)".format(bind, port, port))

    def _on_nic(self, msg):
        try:
            r = json.loads(msg.data)
        except ValueError:
            return
        self.nic[(r.get("host"), r.get("iface"))] = r

    def _on_summary(self, msg):
        try:
            d = json.loads(msg.data)
        except ValueError:
            return
        ports = [{
            "name": "{}/{}".format(h, i),
            "rx": round((r.get("rx_bps") or 0.0) / 1e6, 2),
            "tx": round((r.get("tx_bps") or 0.0) / 1e6, 2),
        } for (h, i), r in sorted(self.nic.items(), key=lambda kv: str(kv[0]))]
        payload = {
            "t": d.get("ts"), "step": d.get("step"), "target_mbps": d.get("target_mbps"),
            "ingress": d.get("switch_ingress_mbps"), "egress": d.get("switch_egress_mbps"),
            "loss_pct": d.get("loss_pct"), "loss_mbps": d.get("loss_mbps"),
            "max_port_mbps": d.get("max_port_mbps"), "nic_rx_drops": d.get("nic_rx_drops"),
            "p50": d.get("lat_p50_ms"), "p95": d.get("lat_p95_ms"), "max": d.get("lat_max_ms"),
            "queueing_p95": d.get("queueing_p95_ms"), "gap_loss": d.get("gap_loss"),
            "port_list": ports,
            "status": {
                "loss": classify(d.get("loss_pct"), self.loss_warn, self.loss_crit),
                "latency": classify(d.get("lat_p95_ms"), self.lat_warn, self.lat_crit),
            },
        }
        self.server.broadcast(json.dumps(payload))

    def destroy_node(self):
        try:
            self.server.shutdown()
        finally:
            super().destroy_node()


def main():
    rclpy.init()
    node = WebMonitor()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
