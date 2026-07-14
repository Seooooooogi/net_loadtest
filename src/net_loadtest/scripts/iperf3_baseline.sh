#!/usr/bin/env bash
# Raw link/switch baseline BEFORE the ROS2 test, so DDS overhead = (iperf3 - ros2) gap.
# Also catches the #1 gotcha: a host that negotiated 1G caps its 2.5G switch port at 1G.
#
#   sink host  :  ./iperf3_baseline.sh server
#   agent host :  ./iperf3_baseline.sh client <sink_ip> [iface]
set -euo pipefail

mode="${1:?usage: $0 server | client <sink_ip> [iface]}"

check_speed() {
  local iface="${1:-}"
  [[ -z "$iface" ]] && return 0
  if command -v ethtool >/dev/null; then
    local speed
    speed="$(ethtool "$iface" 2>/dev/null | awk -F': ' '/Speed:/{print $2}')"
    echo "[link] $iface negotiated: ${speed:-unknown}"
    case "$speed" in
      2500Mb/s) : ;;
      "") echo "[warn] could not read speed (need sudo?)";;
      *) echo "[WARN] $iface is NOT 2.5G ($speed) -> this port is capped below switch line rate";;
    esac
  fi
}

case "$mode" in
  server)
    command -v iperf3 >/dev/null || { echo "install: sudo apt install iperf3"; exit 1; }
    echo "[iperf3] server on :5201 (Ctrl-C to stop)"
    exec iperf3 -s
    ;;
  client)
    ip="${2:?usage: $0 client <sink_ip> [iface]}"
    check_speed "${3:-}"
    command -v iperf3 >/dev/null || { echo "install: sudo apt install iperf3"; exit 1; }
    echo "[iperf3] TCP to $ip ..."; iperf3 -c "$ip" -t 10
    echo "[iperf3] UDP 2.4G probe to $ip (DDS is UDP) ..."; iperf3 -c "$ip" -u -b 2400M -t 10
    ;;
  *) echo "unknown mode: $mode"; exit 1;;
esac
