# net_loadtest_ws

폐쇄망 스위치(예: TP-Link **TL-SG105S-M2**, 5-port 2.5G unmanaged)에서 조별 ROS2/DDS 트래픽을
단계적으로 올리며 **포트별 bps · 스위치 집계 bps · 손실 시작점(감당 한계)** 을 측정하는 colcon 워크스페이스.

측정 원천 = 각 호스트의 **NIC 카운터**(`/sys/class/net/<iface>/statistics`) — unmanaged 스위치라
SNMP 가 없어 각 호스트가 자기 포트의 wire-level tx/rx 를 보고한다. **호스트 1대 = 스위치 포트 1개.**

## 구성

| 경로 | 내용 |
|---|---|
| `src/net_loadtest/` | ROS2 패키지 (ament_python). 노드·측정 정의·전체 사용법 |
| `src/net_loadtest/README.md` | **메인 문서** — 빌드/실행/결과 CSV/웹 대시보드/해석 |
| `src/net_loadtest/scripts/` | `iperf3_baseline.sh`(baseline), `setup-closed-net.sh`(고정 IP + FastDDS whitelist) |
| `docs/DESIGN.md` | 설계 결정·측정 정의·검증 기록 |

`build/` · `install/` · `log/` 는 colcon 산출물이라 추적하지 않는다(재생성 가능).

## Quick start

```bash
# 1) clone + colcon build
git clone git@github.com:Seooooooogi/net_loadtest.git ~/net_loadtest_ws   # private repo (SSH)
cd ~/net_loadtest_ws
colcon build --packages-select net_loadtest
source install/setup.bash

# 2) 폐쇄망 고정 IP + FastDDS whitelist — 각 호스트에서 자기 옥텟 지정 (x = 1..5)
./src/net_loadtest/scripts/setup-closed-net.sh 3        # 먼저 --dry-run 으로 확인 권장
source ~/.bashrc                                        # FastDDS whitelist/RMW 반영
#   옵션: --iface enp3s0 | --ip-only | --dds-only | -y(확인 생략)
```

역할별 실행(요약):

```bash
# sink 1대
ros2 launch net_loadtest loadtest.launch.py role:=sink iface:=<iface>
# 각 조 호스트 (source)
ros2 launch net_loadtest loadtest.launch.py role:=agent iface:=<iface>
# 코디네이터 1대 (ramp + 집계 + 웹 대시보드 http://<ip>:8088/)
ros2 launch net_loadtest loadtest.launch.py role:=coordinator \
  --ros-args --params-file $(ros2 pkg prefix net_loadtest)/share/net_loadtest/config/ramp.yaml
```

파라미터·토폴로지·결과 해석("스위치가 몇 bps 감당?")은 → **[src/net_loadtest/README.md](src/net_loadtest/README.md)**.

## 요구사항

- ROS2 **Humble** 또는 **Jazzy** — 의존성은 `rclpy` + `std_msgs` 뿐(커스텀 msg 없음, std_msgs/String + JSON).
- 측정 호스트마다 유선 iface 이름을 **직접 지정**해야 한다(기본값 없음 — 추측 거부).
- one-way 지연 절대값은 NTP/PTP 클럭 동기 필요. 미동기 시 `queueing_p95_ms`(오프셋 상쇄)만 신뢰.

## License

MIT
