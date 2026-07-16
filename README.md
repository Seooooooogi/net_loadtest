# net_loadtest_ws

폐쇄망 스위치에서 조별 ROS2/DDS 트래픽을 단계적으로 올리며 **포트별 bps · 스위치 집계 bps · 손실 시작점(감당 한계)** 을 측정하는 워크스페이스

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


```bash
ip -br link                              # iface 이름 (호스트마다 다를 수 있음)
sudo ethtool <iface> | grep Speed        # 기대: 2500Mb/s (1G면 그 포트가 병목)
echo 'export ROS_DOMAIN_ID=42' >> ~/.bashrc && source ~/.bashrc   # 5대 동일, 타 강의실과 겹치지 않게
```

**(선택·권장) iperf3 baseline** — DDS 전에 raw 링크 상한 확인:

```bash
./src/net_loadtest/scripts/iperf3_baseline.sh server                 # host1(sink)
./src/net_loadtest/scripts/iperf3_baseline.sh client 10.10.0.1 <iface>  # 각 agent
```

```bash
# [host1] sink
ros2 launch net_loadtest loadtest.launch.py role:=sink iface:=<iface>

# [host2~5] agent
ros2 launch net_loadtest loadtest.launch.py role:=agent iface:=<iface>

# [host1] coordinator
ros2 run net_loadtest aggregator &
ros2 run net_loadtest web_monitor &
ros2 run net_loadtest ramp_controller --ros-args \
  -p "steps_mbps:=[400.0,600.0,800.0,1000.0,1200.0,1600.0]" \
  -p payload_bytes:=65536 -p hold_sec:=20.0 \
  -p shutdown_when_done:=true  
```

**모니터링:**

```bash
http://10.10.0.1:8088/                 # 브라우저(host1)
ros2 topic echo /loadtest/summary      # 터미널 라이브 요약
```


파라미터·토폴로지·결과 해석 → **[src/net_loadtest/README.md](src/net_loadtest/README.md)**.

## 요구사항

- ROS2 **Humble** 또는 **Jazzy** 
- 측정 호스트마다 유선 iface 이름을 **직접 지정**

## License

MIT
