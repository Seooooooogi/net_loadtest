# net_loadtest — 설계 기록

- 일자: 2026-07-13
- 목적: 폐쇄망(협동3 신규 배치, Notion 5번 항목)에서 조별 ROS2/DDS 트래픽을 단계적으로
  올리며 **포트별 bps · 스위치 집계 bps · 감당 한계(손실 시작점)** 측정.
- 대상 스위치: TP-Link **TL-SG105S-M2** — 5-port 100M/1G/2.5G, **unmanaged**(SNMP 없음),
  스위칭 용량 25 Gbps(논블로킹), 패킷버퍼 8 Mbit, IGMP snooping.

## 확정 결정

- **측정 계층 = 호스트 NIC 카운터** (`/sys/class/net/<iface>/statistics`). unmanaged 라 SNMP 불가 →
  각 호스트가 자기 포트의 wire-level tx/rx 를 보고. 호스트 1 = 포트 1.
- **부하 생성 = 얇은 커스텀 `load_gen`** (rclpy + std_msgs). 전 호스트에 `performance_test` 빌드
  강요를 피함. jazzy/humble 양쪽 빌드. performance_test 위임은 옵션.
- **위치 = 별도 워크스페이스** `~/net_loadtest_ws`. 설치 레포(base 환경 전용)와 분리.
- **토폴로지 = many-to-one 수렴**. 논블로킹 스위치에서 한계가 드러나는 유일한 stress 패턴.
- **메시지 = std_msgs/String + JSON**. 커스텀 .msg/rosidl 빌드 회피(ament_python 단독).

## 컴포넌트 / 데이터 흐름

```
ramp_controller ──/loadtest/step(latched)──▶ load_gen(source)×N ──/loadtest/traffic──▶ load_gen(sink)
   (코디네이터)                                    │                                        │
                                          각 호스트 nic_reporter ──/loadtest/nic──▶ aggregator ──▶ CSV + /loadtest/summary
```

- `nic_reporter`: iface 폴링, 델타/interval → bps/pps/drop. iface 는 **기본값 없는 필수 파라미터**(추측 거부).
- `load_gen`: source=설정 payload×rate 발행(rate 는 step 이 주입), sink=수신. QoS reliable/best_effort 선택.
- `ramp_controller`: steps_mbps 리스트를 hold_sec 마다 브로드캐스트. latched 라 late-join source 도 현재 step 수신.
- `aggregator`: Σtx=ingress, Σrx=egress, loss=ingress−egress. CSV append-only + run별 파일명.

## 측정 정의 (핵심)

- 포트별 bps = 각 reporter rx/tx (wire, 헤더·RTPS 포함).
- 스위치 집계 = Σingress ≈ Σegress.
- **감당 한계 = loss_pct 가 0 에서 이탈하는 offered load** (peak bps 아님). TL-SG105S-M2 는 논블로킹이라
  벽은 ① sink 포트 2.5G, ② 8 Mbit 버퍼(버스트 드롭), ③ IGMP/멀티캐스트 discovery.

## 검증 (2026-07-13, humble 로컬)

- 유닛테스트 `test/test_rates.py` 5/5 통과 (bps=bytes×8, wrap/0-interval 가드 → None, loss clamp, rate_hz).
- `colcon build` 성공.
- `lo` 루프백 E2E 스모크: source(50Mbps) → sink(7620 msgs 수신), aggregator `in 51.2/out 51.2 Mbps loss 0.0%`,
  CSV 정상. 측정 wire(51.2) > goodput(50) 로 오버헤드 검출 확인. (실제 2.5G 수치 검증 아님 — 타깃 폐쇄망에서 수행.)

## v0.2 추가 (2026-07-14)

- **per-packet 지연**: source payload 에 `src|seq|send_ts` 헤더(`packet.py`). sink 가 one-way 지연
  (p50/p95/max) + seq gap 손실 산출 → `/loadtest/latency`. `queueing_p95_ms = p95 − min` 으로 클럭
  오프셋 상쇄(NTP 미동기여도 congestion 지연 유효). aggregator 가 summary CSV 에 병합.
- **소스 통합**: `ext_source` 어댑터 — `/loadtest/step` 구동 command-template 러너로 performance_test
  등 외부 생성기를 ramp 에 통합. perf_test CLI 버전차 회피 위해 flag 하드코딩 대신 placeholder 템플릿
  (`{rate}{mbps}{payload}{seconds}`). launch `source:=ext`. 미설치 시 비-fatal skip.
- 검증(humble 로컬): 유닛 12/12(rates 5 + packet 7), `lo` 스모크에서 sink latency(p50 0.06 p95 0.10ms)·
  aggregator 병합·summary CSV latency 컬럼·ext_source step별 spawn 확인.

## v0.3 추가 (2026-07-14) — 실시간 웹 대시보드

- **`web_monitor` 노드**: rclpy 구독(`/loadtest/summary`+`/loadtest/nic`) + stdlib `http.server`
  (ThreadingHTTPServer) + **SSE**. 브라우저에 ROS/외부 의존 0 → 폐쇄망 오프라인 동작. 클라이언트당
  1스레드, ROS 콜백이 각 큐로 push, 신규 접속 시 backlog(기본 300) replay 로 새로고침해도 차트 유지.
- **페이지**(`web_ui.py`, self-contained): 다크 우선 dev-tool 미학(ref awesome-design-md — 브랜드
  DESIGN.md 모음, Cursor/Warp/Raycast 계열). 색 = **dataviz 검증 팔레트**(validate_palette.js PASS:
  latency 3색 worst ΔE 35.9, switch 2색 69.8). 손수 그린 canvas 라인차트(라이브러리 0) + hover
  crosshair, stat 타일(임계값 색), 포트별 bps 바. 라이트/다크 both, tabular-nums.
- 왜 Artifact 아님: claude.ai Artifact 는 외부 fetch 차단·정적이라 폐쇄망 live 토픽 구독 불가 →
  ROS 노드 self-serve.
- 검증(humble 로컬): 유닛 13개(+classify), `GET /` 200·11KB, `GET /events` SSE 라이브(4s 7 events,
  전 필드 정상), 인라인 JS `node --check` PASS, DOM 앵커·SSE 배선 확인. **육안 렌더 확인은 타깃 브라우저에서.**

## 미결 / 향후

- `load_gen` timer rate 천장(수 kHz) → 높은 throughput 은 payload_bytes 로.
- one-way 지연 절대값은 NTP 동기 의존(queueing 은 무관).
- 강의실 전체(스위치 다단) 집계는 스위치별 리그 반복 후 합산.
- 대시보드 히스토리 브라우저 window(120) 만 — 장기 추세는 summary CSV 로.
