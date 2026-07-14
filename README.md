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
git clone https://github.com/Seooooooogi/net_loadtest.git ~/net_loadtest_ws   # private repo (인증 필요)
cd ~/net_loadtest_ws
colcon build --packages-select net_loadtest
source install/setup.bash

# 2) 폐쇄망 고정 IP + FastDDS whitelist — 각 호스트에서 자기 옥텟 지정 (x = 1..5)
./src/net_loadtest/scripts/setup-closed-net.sh 3        # 먼저 --dry-run 으로 확인 권장
source ~/.bashrc                                        # FastDDS whitelist/RMW 반영
#   옵션: --iface enp3s0 | --ip-only | --dds-only | -y(확인 생략)
```

## 부하 테스트 실행 (5대 예시)

5포트 스위치 = **4대 source → 1대 sink 수렴**(논블로킹 스위치에서 한계가 드러나는 패턴), 코디네이터는
sink 호스트에 co-locate. 5포트 전부 `nic_reporter` 로 측정된다.

| 호스트 | setup 스크립트 x → IP | 역할 |
|---|---|---|
| host1 | 1 → 10.10.0.1 | **sink + coordinator**(ramp·집계·웹) |
| host2~5 | 2~5 | agent(source) |

각 호스트 준비 = 위 Quick start 1~2 (clone/build + `setup-closed-net.sh <x> --iface <iface>`). 추가로 5대 모두
같은 `ROS_DOMAIN_ID` + 유선 iface 이름·2.5G 확인:

```bash
ip -br link                              # iface 이름 (호스트마다 다를 수 있음)
sudo ethtool <iface> | grep Speed        # 기대: 2500Mb/s (1G면 그 포트가 병목)
echo 'export ROS_DOMAIN_ID=42' >> ~/.bashrc && source ~/.bashrc   # 5대 동일, 타 강의실과 겹치지 않게
```

**(선택·권장) iperf3 baseline** — DDS 전에 raw 링크 상한 확인(DDS 오버헤드 = iperf3 − ROS2 delivered):

```bash
./src/net_loadtest/scripts/iperf3_baseline.sh server                 # host1(sink)
./src/net_loadtest/scripts/iperf3_baseline.sh client 10.10.0.1 <iface>  # 각 agent
```

**실행 순서가 중요** — sink → agents(대기) → coordinator(마지막에 램프 시작). 각 명령은 별도 터미널(또는 `&`):

```bash
# [host1] sink (수신 + nic_reporter)
ros2 launch net_loadtest loadtest.launch.py role:=sink iface:=<iface>

# [host2~5] agent (source + nic_reporter) — 4대 모두. step 오기 전엔 idle.
ros2 launch net_loadtest loadtest.launch.py role:=agent iface:=<iface>

# [host1] coordinator — 마지막에. 여기서 램프 시작.
ros2 run net_loadtest aggregator &
ros2 run net_loadtest web_monitor &
ros2 run net_loadtest ramp_controller --ros-args \
  -p "steps_mbps:=[400.0,600.0,800.0,1000.0,1200.0,1600.0]" \
  -p payload_bytes:=65536 -p hold_sec:=20.0 \
  -p shutdown_when_done:=true          # 마지막 스텝 후 전 노드 자동 종료(5대 수동 Ctrl-C 불필요)
```

> **payload 를 64KB 로 키우는 이유(중요)**: `load_gen` 은 timer 기반이라 발행 rate 가 `max_rate_hz`(기본
> 5000)에서 막힌다. 소스당 처리량 상한 = `max_rate_hz × payload × 8`. payload 4096B 면 소스당 **~164 Mbps**
> 에서 잘려(target 을 아무리 올려도 무효), 4소스 집계가 ~0.7 Gbps 밖에 안 나온다. payload 65536B 면 상한이
> `5000×65536×8 = 2.6 Gbps/소스` 로 올라가 target 1600 까지 도달, 4소스 집계가 2.5G 를 넘겨 스위치가 포화된다.
>
> **감당 한계 판독**: sink 포트 2.5 Gbps 는 per-source ~625(4×625=2500)에서 이미 넘는다. offered 를 올리며
> **wire `loss_pct`(= Σtx−sink rx)가 0 에서 뜨는 지점 = 스위치 한계**. 단 Python `load_gen`/sink 가 먼저
> CPU-cap 될 수 있어(소스 tx 가 target 에 못 미치거나 `gap_loss` 만 급증) — 그건 **생성기/sink 한계지 스위치
> 한계가 아니다**. 순수 스위치 상한은 `iperf3` baseline(단일 흐름 ~2.38 Gbps)이 더 확실하다.
>
> **자동 종료 vs loop**: `shutdown_when_done:=true` = 램프 1회 후 전 노드 자동 종료(권장, 원샷 테스트).
> `loop:=true` = 램프 무한 반복(Ctrl-C 종료). 둘 다 생략 시 = 마지막 스텝 후 idle 상태로 대기.

**모니터링:**

```bash
http://10.10.0.1:8088/                 # 브라우저(코디네이터=host1). 방화벽 시 host1: sudo ufw allow 8088
ros2 topic echo /loadtest/summary      # 또는 터미널 라이브 요약
```

결과 CSV(host1): `~/loadtest_runs/loadtest_<타임스탬프>_summary.csv` (스텝별 bps·손실·지연).
멈출 땐 각 호스트 Ctrl-C (coordinator background 는 `kill %1 %2`).

파라미터·토폴로지·결과 해석("스위치가 몇 bps 감당?")은 → **[src/net_loadtest/README.md](src/net_loadtest/README.md)**.

## 요구사항

- ROS2 **Humble** 또는 **Jazzy** — 의존성은 `rclpy` + `std_msgs` 뿐(커스텀 msg 없음, std_msgs/String + JSON).
- 측정 호스트마다 유선 iface 이름을 **직접 지정**해야 한다(기본값 없음 — 추측 거부).
- one-way 지연 절대값은 NTP/PTP 클럭 동기 필요. 미동기 시 `queueing_p95_ms`(오프셋 상쇄)만 신뢰.

## License

MIT
