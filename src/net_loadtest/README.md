# net_loadtest

폐쇄망 스위치(예: TP-Link TL-SG105S-M2, 5-port 2.5G **unmanaged**)에서 조별 ROS2/DDS
트래픽을 **단계적으로 올리며** 포트별 bps · 스위치 집계 bps · **손실 시작 지점(감당 한계)**
을 측정한다. unmanaged 스위치라 SNMP가 없으므로 **각 호스트의 NIC 카운터**
(`/sys/class/net/<iface>/statistics`)를 wire-level 측정점으로 쓴다. 호스트 1대 = 스위치 포트 1개.

> 이 패키지는 특정 워크스테이션에 묶이지 않는다. iface·호스트명·IP를 하드코딩하지 않으며,
> iface는 **호스트마다 반드시 지정**해야 하는 파라미터다(추측 거부).

## 노드

| 노드 | 실행 위치 | 하는 일 |
|---|---|---|
| `nic_reporter` | 측정할 모든 호스트 | NIC 카운터 폴링 → 포트별 rx/tx bps·pps·drop 을 `/loadtest/nic` 로 발행 |
| `load_gen` (mode=source) | 조별 호스트 | `src\|seq\|send_ts` 헤더 + 설정 크기 payload 를 코디네이터가 준 rate 로 발행 |
| `load_gen` (mode=sink) | 수렴 대상 1대 | 수신 → **one-way 지연**(p50/p95/max·큐잉) + **seq gap 손실**(앱 레벨)을 `/loadtest/latency` 로 발행 |
| `ext_source` | 조별 호스트(옵션) | `load_gen` 대신 **performance_test 등 외부 생성기**를 ramp 구동 — 소스 통합 |
| `ramp_controller` | 코디네이터 1대 | 단계 스케줄을 `/loadtest/step` 로 브로드캐스트(latched) |
| `aggregator` | 코디네이터 1대 | nic + latency feed 합산 → 스위치 집계·손실·지연, CSV 2개(detail/summary) + `/loadtest/summary` |
| `web_monitor` | 코디네이터 1대 | `/loadtest/summary`+`/loadtest/nic` → 브라우저 **실시간 대시보드**(SSE, 무외부의존) |

토폴로지 기본값 = **many-to-one 수렴**: 논블로킹 스위치(패브릭 25 Gbps)에서 한계를
드러내는 건 all-to-all 이 아니라 N개 소스가 1개 sink 의 2.5G 포트로 몰릴 때의 포트 포화 +
8 Mbit 버퍼 드롭이다.

## 사전 준비 (타깃 호스트마다)

```bash
# 1) 유선 iface 이름 확인 (호스트마다 다름)
ip -br link

# 2) 그 포트가 실제 2.5G 로 협상됐는지 확인 — 1G 로 붙으면 그 포트는 스위치 line-rate 미달
ethtool <iface> | grep Speed        # 기대: 2500Mb/s

# 3) 모든 호스트 같은 ROS_DOMAIN_ID + 같은 서브넷(폐쇄망), 방화벽에서 DDS 허용

# 4) one-way 지연 측정은 클럭 동기 필요 — 폐쇄망에 chrony/NTP 서버 1대 두고 전 호스트 동기.
#    미동기여도 queueing_p95_ms(= p95 - min)는 상수 오프셋이 상쇄돼 congestion 지연은 유효.
sudo apt install chrony && chronyc tracking   # offset 확인
```

#### 폐쇄망 IP + FastDDS whitelist 자동 설정 (TP-Link 실사용 편의)

`scripts/setup-closed-net.sh` 가 위 1~2번을 자동화한다: 유선 NIC 고정 IP `10.10.0.<x>/24`
(게이트웨이/DNS 없음·never-default → wifi 인터넷 경로 보호) + FastDDS `interfaceWhiteList`
= `127.0.0.1` + `10.10.0.1..5` 허용(DDS 를 폐쇄망 NIC + loopback 에만 바인딩, docker0/tailscale0 등 차단).

```bash
# 각 호스트에서 자기 옥텟만 지정 (x = 1..5). 먼저 --dry-run 으로 확인 권장.
scripts/setup-closed-net.sh 3 --dry-run
scripts/setup-closed-net.sh 3            # 적용(확인 프롬프트), 새 터미널/ source ~/.bashrc 후 DDS 반영
#   --iface enp3s0   NIC 지정   |   --ip-only / --dds-only   |   -y  확인 생략
```

> 이 스크립트는 **RMW 를 `rmw_fastrtps_cpp` 로 고정**한다(whitelist 는 FastDDS 기능). FastDDS 는
> Humble 기본 RMW 지만, 이 프로젝트 호스트는 base 설치가 CycloneDDS 로 override 해둬서 명시 고정이
> 필요(profiles 파일은 FastDDS 만 읽음). 기존 cyclonedds 블록보다 뒤에 와서 우선(스크립트가 감지·경고).
> whitelist 는 동일 XML 을 5대 전부에 배포 가능 — `interfaceWhiteList` 는 로컬 인터페이스만 필터하므로
> 각 호스트는 자기 IP + `127.0.0.1` 만 매칭. **loopback 포함 필수** — `useBuiltinTransports=false` 로
> SHM 까지 꺼서, loopback 없으면 같은 호스트 노드(coordinator 의 aggregator/ramp/web, ros2 daemon/CLI)
> 통신이 깨진다. (Fast DDS 3.x 는 `interfaces/allowlist` 로 개명 — XML 주석에 명시.)

빌드:

```bash
cd ~/net_loadtest_ws
colcon build --packages-select net_loadtest
source install/setup.bash
```

## 실행

먼저 **iperf3 baseline**(선택이지만 권장 — DDS 오버헤드 = iperf3 - ros2 gap):

```bash
# sink 호스트
./src/net_loadtest/scripts/iperf3_baseline.sh server
# 각 조 호스트 (iface 넘기면 2.5G 협상 자동 점검)
./src/net_loadtest/scripts/iperf3_baseline.sh client <sink_ip> <iface>
```

ROS2 부하 테스트:

```bash
# sink 호스트 1대
ros2 launch net_loadtest loadtest.launch.py role:=sink iface:=<iface>

# 각 조 호스트 (source)
ros2 launch net_loadtest loadtest.launch.py role:=agent iface:=<iface>

# 코디네이터 1대 (ramp + 집계 + 웹) — 기본 램프로 바로 실행
ros2 launch net_loadtest loadtest.launch.py role:=coordinator
# 램프 스케줄을 바꾸려면 노드를 직접 실행 (launch 는 params-file 을 노드로 전달하지 않음):
#   ros2 run net_loadtest aggregator & ros2 run net_loadtest web_monitor &
#   ros2 run net_loadtest ramp_controller --ros-args \
#     -p "steps_mbps:=[50.0,100.0,200.0,400.0,600.0,800.0]" -p hold_sec:=20.0

# 라이브 요약
ros2 topic echo /loadtest/summary
```

### 로그 (CSV) — 각 항목 설명

`aggregator`(코디네이터)가 실행 내내 `~/loadtest_runs/` 에 **append-only, run 별 타임스탬프 파일** 2개를
기록한다(매 행 flush → Ctrl-C 해도 직전까지 유실 없음). 로그는 코디네이터 호스트 한 곳에 모인다.

**`loadtest_<ts>.csv` — 포트별 상세** (한 행 = 한 포트의 한 샘플, nic_reporter 원본):

| 컬럼 | 단위 | 뜻 |
|---|---|---|
| `ts` | epoch 초 | 샘플 시각 |
| `step` | 정수 | 램프 단계 인덱스(0부터). `-1` = 램프 시작 전 |
| `target_mbps` | Mbps | 그 단계의 **소스 1대당** offered 목표 |
| `host` / `iface` | — | 보고 호스트 / NIC (= 스위치 포트 식별) |
| `rx_bps` / `tx_bps` | **bits/s** | 그 포트 수신/송신 **wire** 속도(헤더·RTPS 포함) |
| `rx_pps` / `tx_pps` | packets/s | 초당 패킷 수 |
| `rx_drop` / `tx_drop` | 개수 | 그 간격에 **NIC(호스트)** 가 버린 패킷(수신 호스트가 못 따라감) |

**`loadtest_<ts>_summary.csv` — 스위치 집계 + 지연** (초당 1행, **분석용 메인 테이블**):

| 컬럼 | 단위 | 뜻 |
|---|---|---|
| `ts` / `step` / `target_mbps` | — | 위와 동일(target 은 소스 1대당) |
| `ports` | 개수 | 집계에 들어온 포트 수(= nic_reporter 도는 호스트 수) |
| `switch_ingress_mbps` | Mbps | **Σ 모든 포트 tx** = 스위치로 들어간 총량(offered) |
| `switch_egress_mbps` | Mbps | **Σ 모든 포트 rx** = 스위치가 내보낸 총량(delivered) |
| `loss_mbps` / `loss_pct` | Mbps / % | `ingress − egress` = **스위치/수신단 드롭**. 0 = 무손실 |
| `max_port_mbps` | Mbps | 가장 바쁜 단일 포트(보통 sink). 2.5G 근접 = 포트 포화 |
| `nic_rx_drops` | 개수 | 전 포트 NIC rx drop 합 |
| `lat_p50_ms` / `lat_p95_ms` / `lat_max_ms` | ms | sink one-way 지연 분위수 / 최대 |
| `queueing_p95_ms` | ms | `p95 − 최소관측` = **버퍼 큐잉 지연**(클럭 오프셋 상쇄, NTP 미동기여도 유효) |
| `gap_loss` | 개수 | **앱 레벨** 손실(소스별 seq 결번 누적) |

> 단위 주의: **포트별 CSV 는 bps(bits/s), 요약 CSV 는 Mbps** (`mbps = bps / 1e6`). 라이브로는
> `ros2 topic echo /loadtest/summary` 또는 웹 대시보드가 같은 값을 보여준다.

### 웹 대시보드 (실시간 모니터링)

코디네이터 launch 에 `web_monitor` 가 포함 → 브라우저에서 **`http://<코디네이터-IP>:8088/`** 접속.
`/loadtest/summary`+`/loadtest/nic` 을 **SSE** 로 라이브 푸시(브라우저에 ROS 불필요, 외부 JS/CSS/폰트
0 → 폐쇄망·오프라인 동작). 스위치 throughput(ingress/egress) · 지연(p50/p95/max) 라인차트 +
손실·큐잉·gap_loss stat 타일(임계값 색상) + 포트별 bps 바. 다크 우선(dev-tool 미학, ref
awesome-design-md), 색은 검증된 dataviz 팔레트.

```bash
# 코디네이터 launch 가 자동 기동. 포트 바꾸려면:
ros2 launch net_loadtest loadtest.launch.py role:=coordinator web_port:=9000 ...
# 단독 실행도 가능:  ros2 run net_loadtest web_monitor --ros-args -p port:=8088
```

> 폐쇄망 방화벽 사용 시 포트 개방 필요: `sudo ufw allow 8088`. 임계값은 파라미터
> (`loss_warn_pct`/`loss_crit_pct`/`lat_warn_ms`/`lat_crit_ms`)로 조정.

### 소스 통합 — performance_test 등 외부 생성기

`load_gen` 대신 외부 DDS 벤치를 소스로 쓰고, 측정은 동일 stack(nic_reporter/aggregator)으로.
ext_source 가 `/loadtest/step` 을 받아 step 마다 명령을 실행(placeholder `{rate}` `{mbps}`
`{payload}` `{seconds}` 치환). perf_test CLI 는 버전마다 다르니 `--help` 로 확인 후 템플릿 지정.

```bash
# 조 호스트: 외부 소스로 전환
ros2 launch net_loadtest loadtest.launch.py role:=agent iface:=<iface> source:=ext \
  source_cmd:="perf_test -c ROS2 -m Array4k --rate {rate} --max-runtime {seconds} -p 1 -s 0"
```

perf_test 트래픽엔 seq 헤더가 없어 sink 의 latency/gap 는 `foreign` 으로 집계되지 않는다 —
그때 지연은 perf_test 자체 리포트에서 보고, 이 stack 은 스위치 레벨 bps/손실을 담당(상보적).
perf_test 미설치면 ext_source 가 설치 안내 후 해당 step 을 skip(비-fatal).

## 해석 — "스위치가 몇 bps 감당?"

- **포트별 bps** = 각 `nic_reporter` 의 rx_bps/tx_bps (헤더·RTPS 오버헤드 포함 wire-level).
- **스위치 집계** = Σtx_bps(ingress) ≈ Σrx_bps(egress). 정상 구간에선 둘이 같다.
- **지연** = sink one-way p50/p95/max(ms). `queueing_p95_ms`(= p95 − 최소관측)는 클럭 오프셋을
  상쇄한 **버퍼 큐잉 지연** — 부하가 오르며 이게 치솟는 지점이 8 Mbit 버퍼 포화 신호.
- **앱 레벨 손실** = `gap_loss`(소스별 seq 결번). NIC `loss_pct`(wire)와 상보 — 둘 다 보면 스위치
  드롭 vs 수신 호스트 드롭 구분에 도움.
- **감당 한계** = offered 를 올릴 때 **`loss_pct`/`gap_loss` 가 0 에서 뜨거나 `queueing_p95` 급증하는
  지점**. peak bps 가 아니라 **손실·지연 시작점**이 답이다.
- TL-SG105S-M2 는 논블로킹(25 Gbps)이라 패브릭 자체가 병목이 되긴 어렵다. 실제로 보이는 벽:
  ① sink 포트 2.5G line-rate, ② 8 Mbit 버퍼(버스트 many-to-one 시 드롭), ③ IGMP snooping /
  DDS 멀티캐스트 discovery 플러딩(도메인 ID 분리 한계와 직결).
- 5포트 = 스위치 1대당 최대 5호스트. 강의실 전체는 스위치 다단 → 스위치별로 이 리그 반복.

### 분석 방법 (summary CSV)

목표 = **감당 한계 = offered(`switch_ingress_mbps`)를 올릴 때 손실/지연이 꺾이는 지점** 찾기.

1. **스텝별 요약**: `step` 으로 group → 스텝마다 평균 offered(`switch_ingress_mbps`)·`loss_pct`·
   `queueing_p95_ms`·`gap_loss`·`max_port_mbps`.
2. **한계 = `loss_pct` 가 0 → 양수로 처음 뜨는 스텝**(또는 `queueing_p95_ms` 급등 / `gap_loss` 증가 시작).
   그 **직전 스텝의 offered = 무손실로 감당한 최대 bps**.
3. **드롭 위치 구분**: `loss_mbps`(=ingress−egress, wire)와 `gap_loss`(앱)가 함께 오르면 스위치가 흘리는 것,
   `nic_rx_drops` 만 오르면 수신 호스트가 못 따라가는 것(sink CPU/버퍼). `max_port_mbps` 가 2.5G 에
   붙었으면 sink 포트 line-rate 포화.

```python
import pandas as pd
d = pd.read_csv("loadtest_<ts>_summary.csv")
g = d.groupby("step").agg(offered=("switch_ingress_mbps","mean"),
                          delivered=("switch_egress_mbps","mean"),
                          loss_pct=("loss_pct","max"),
                          q95_ms=("queueing_p95_ms","max"),
                          gap=("gap_loss","max")).reset_index()
print(g)
limit = g.loc[g.loss_pct < 0.5, "offered"].max()   # 임계 0.5% 예시
print("무손실 감당 한계 ≈ %.0f Mbps" % limit)
```

포트별 상세 CSV 는 `groupby(["host","iface"])` 로 각 포트 기여도·느린(1G) 포트 탐지에 쓴다.

## 기존 도구와의 관계 (하이브리드)

- `iperf3` — raw 링크/포트 상한(ground truth). 이 패키지의 baseline.
- `performance_test`(Apex.AI/Eclipse) — 순수 DDS 처리량·지연 벤치. 더 정밀한 DDS 분석이 필요하면
  `load_gen` 대신 소스로 끼울 수 있다(옵션). 강의실 전 호스트에 빌드 강요를 피하려고 기본은 얇은 커스텀.
- `ros2 topic bw`/`hz` — 앱 goodput 즉석 확인용.
- NIC 카운터(`sar -n DEV`, `bmon`, `ifstat`) — 이 패키지가 하는 것과 동일한 원천, 여기선 ROS 토픽으로 집계.

## 알려진 한계 (ponytail)

- `load_gen` 은 timer 기반이라 발행 rate 가 수 kHz 에서 천장. 더 높은 throughput 은 rate 가 아니라
  `payload_bytes` 를 키워서 낸다(경고 로그로 안내).
- one-way 지연 절대값은 NTP/PTP 동기에 의존. 미동기 시 `queueing_p95_ms`(오프셋 상쇄)만 신뢰.
- sink latency 샘플은 window 당 `sample_cap`(기본 20000) 로 제한 — 초고rate 에서 p95 가 약간 낙관적일 수 있음.
- 손실 집계는 **모든 활성 포트가 `nic_reporter` 를 돌릴 때만** 정확(미관측 포트는 egress 과소계상).
