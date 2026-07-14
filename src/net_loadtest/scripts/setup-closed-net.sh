#!/usr/bin/env bash
# setup-closed-net.sh — TP-Link 폐쇄망 실사용 편의 셋업.
#   1) 유선 NIC 에 고정 IP 10.10.0.<x>/24 (게이트웨이/DNS 없음, never-default → wifi 인터넷 경로 보호).
#   2) ROS2 FastDDS interfaceWhiteList = 10.10.0.1..5 만 허용 → DDS 를 폐쇄망 NIC 에만 바인딩
#      (docker0/tailscale0 등 타 인터페이스로 새는 것 차단, 도메인 ID 한계 보완).
#
# 사용:  setup-closed-net.sh <x> [옵션]
#   <x>            이 호스트의 마지막 옥텟 → 10.10.0.<x> (허용 범위 1..5). --dds-only 시 생략 가능.
#   --iface <name> 유선 NIC 지정 (기본: 물리 유선 NIC 자동 탐지)
#   --ip-only      IP 설정만       --dds-only  FastDDS whitelist 만
#   --dry-run      바꾸지 않고 실행할 내용만 출력
#   -y, --yes      확인 프롬프트 생략
#   -h, --help
#
# 멱등: 여러 번 실행해도 결과 동일. state 관리 없음(단독 실행 스크립트).
set -euo pipefail

# --- 바꾸려면 여기만 수정 (subnet / whitelist 범위) ---------------------------
SUBNET_BASE="10.10.0"       # 10.10.0.x
PREFIX=24
WL_START=1                  # whitelist 시작 옥텟
WL_COUNT=5                  # 개수 → 기본 10.10.0.1 .. 10.10.0.5
FASTDDS_XML="${HOME}/.config/net_loadtest/fastdds_whitelist.xml"
BEGIN_MARK="# >>> net_loadtest closed-net env >>>"
END_MARK="# <<< net_loadtest closed-net env <<<"

# --- 인자 파싱 ---------------------------------------------------------------
X=""; IFACE=""; DO_IP=1; DO_DDS=1; DRY=0; YES=0
usage(){ sed -n '2,20p' "$0"; }
while [[ $# -gt 0 ]]; do
    case "$1" in
        --iface) IFACE="${2:?--iface 뒤에 NIC 이름 필요}"; shift 2 ;;
        --ip-only)  DO_DDS=0; shift ;;
        --dds-only) DO_IP=0;  shift ;;
        --dry-run)  DRY=1; shift ;;
        -y|--yes)   YES=1; shift ;;
        -h|--help)  usage; exit 0 ;;
        -*) echo "unknown option: $1" >&2; usage; exit 2 ;;
        *)  X="$1"; shift ;;
    esac
done

WL_END=$((WL_START + WL_COUNT - 1))
if ((DO_IP)); then
    [[ -n "${X}" ]] || { echo "error: <x> 필요 (10.10.0.<x>). 예) setup-closed-net.sh 3" >&2; exit 2; }
    [[ "${X}" =~ ^[0-9]+$ ]] || { echo "error: <x> 는 정수여야 함: '${X}'" >&2; exit 2; }
    if (( X < WL_START || X > WL_END )); then
        echo "error: <x>=${X} 는 whitelist 범위(${WL_START}..${WL_END}) 밖 → 이 IP 는 화이트리스트에 없어 DDS 가 바인딩 못 함." >&2
        exit 2
    fi
fi
HOST_IP="${SUBNET_BASE}.${X}"

run(){ printf '  + %s\n' "$*"; if ((DRY)); then return 0; fi; "$@"; }

# --- 확인 --------------------------------------------------------------------
echo "== 폐쇄망 셋업 계획 =="
((DO_IP))  && echo "  - 고정 IP : ${HOST_IP}/${PREFIX} (게이트웨이/DNS 없음, never-default)"
((DO_DDS)) && echo "  - FastDDS : whitelist ${SUBNET_BASE}.${WL_START}..${SUBNET_BASE}.${WL_END}, RMW=rmw_fastrtps_cpp"
((DO_DDS)) && echo "              XML=${FASTDDS_XML}, ~/.bashrc 관리 블록 갱신"
((DRY)) && echo "  (DRY-RUN — 아무것도 바꾸지 않음)"
if ((DO_DDS)) && grep -q "cyclonedds env" "${HOME}/.bashrc" 2>/dev/null; then
    echo "  ! 주의: ~/.bashrc 에 기존 CycloneDDS 설정 블록 존재 → 이 블록이 뒤에 와서 RMW 를 FastDDS 로 덮어씀."
fi
if ((!DRY)) && ((!YES)); then
    if [[ ! -t 0 ]]; then echo "비대화형 실행 — 확인 생략하려면 -y 필요." >&2; exit 1; fi
    read -r -p "적용할까요? [y/N] " ans
    [[ "${ans}" =~ ^[Yy]$ ]] || { echo "취소됨."; exit 0; }
fi

# =============================================================================
# 1) 고정 IP (nmcli, never-default — 검증된 방식 재사용)
# =============================================================================
setup_ip(){
    command -v nmcli >/dev/null || { echo "[ip] nmcli 없음 — NetworkManager 환경 아님." >&2; return 1; }

    local nic="${IFACE}"
    if [[ -z "${nic}" ]]; then
        local -a found=()
        local path n
        for path in /sys/class/net/*; do
            n="$(basename "${path}")"
            [[ "${n}" == "lo" ]] && continue
            case "${n}" in docker*|veth*|br-*|virbr*|bond*|tap*|tun*) continue ;; esac
            [[ -e "${path}/wireless" ]] && continue   # 폐쇄망 = 유선
            [[ -e "${path}/device" ]]   || continue   # 물리 NIC 만
            found+=("${n}")
        done
        [[ "${#found[@]}" -gt 0 ]] || { echo "[ip] 유선 NIC 자동탐지 실패 — --iface <name> 로 지정." >&2; return 1; }
        nic="${found[0]}"
        [[ "${#found[@]}" -gt 1 ]] && echo "[ip] 유선 NIC 여러 개(${found[*]}) → '${nic}' 사용. 정확히 하려면 --iface."
        echo "[ip] 유선 NIC 자동탐지 → ${nic}"
    fi

    # NM connection 결정: 활성 → 저장된 ethernet 프로필 → 없으면 생성
    local conn
    conn="$(nmcli -t -f NAME,DEVICE con show --active 2>/dev/null | awk -F: -v d="${nic}" '$2==d{print $1; exit}')"
    if [[ -z "${conn}" ]]; then
        local name ifn
        while IFS= read -r name; do
            [[ -z "${name}" ]] && continue
            [[ "$(nmcli -g connection.type con show "${name}" 2>/dev/null)" == "802-3-ethernet" ]] || continue
            ifn="$(nmcli -g connection.interface-name con show "${name}" 2>/dev/null)"
            if [[ "${ifn}" == "${nic}" || -z "${ifn}" ]]; then conn="${name}"; break; fi
        done < <(nmcli -t -f NAME con show 2>/dev/null)
    fi
    if [[ -z "${conn}" ]]; then
        conn="${nic}-closednet"
        echo "[ip] '${nic}' ethernet 프로필 없음 → 생성: ${conn}"
        run nmcli con add type ethernet ifname "${nic}" con-name "${conn}"
    fi
    echo "[ip] 대상 connection: ${conn} (device ${nic})"

    run nmcli con modify "${conn}" \
        connection.interface-name "${nic}" \
        connection.autoconnect yes \
        ipv4.method manual \
        ipv4.addresses "${HOST_IP}/${PREFIX}" \
        ipv4.gateway "" \
        ipv4.dns "" \
        ipv4.never-default yes
    echo "[ip] 설정: ${HOST_IP}/${PREFIX} (게이트웨이/DNS 없음, never-default)"

    if ((DRY)); then return 0; fi
    if nmcli con up "${conn}" >/dev/null 2>&1; then echo "[ip] 활성화 완료."
    else echo "[ip] 경고: 활성화 실패(케이블 미연결 가능) — 설정은 저장됨, 연결 시 적용." >&2; fi
    local applied
    applied="$(nmcli -g IP4.ADDRESS device show "${nic}" 2>/dev/null | head -1 || true)"
    if [[ "${applied}" == "${HOST_IP}/${PREFIX}" ]]; then echo "[ip] 검증 OK: ${nic} = ${applied}"
    else echo "[ip] 현재 ${nic} 주소: ${applied:-(none/down)} (기대 ${HOST_IP}/${PREFIX} — 케이블 연결 시 적용)"; fi
}

# =============================================================================
# 2) FastDDS interfaceWhiteList
# =============================================================================
setup_dds(){
    # whitelist <address> 블록 생성.
    # 127.0.0.1 을 항상 포함 — builtin(SHM 포함) 을 끈 상태라 loopback 이 없으면 같은 호스트 노드
    # (coordinator 의 aggregator/ramp/web_monitor, ros2 daemon/CLI) 끼리 통신이 깨진다. loopback 은
    # 스위치를 지나지 않아 포트별 측정에 영향 없고, 타 NIC 격리도 유지됨.
    local wl="                    <address>127.0.0.1</address>"$'\n'
    local i
    for ((i=WL_START; i<=WL_END; i++)); do
        wl+="                    <address>${SUBNET_BASE}.${i}</address>"$'\n'
    done

    echo "[dds] XML 렌더링 → ${FASTDDS_XML}"
    if ((!DRY)); then
        mkdir -p "$(dirname "${FASTDDS_XML}")"
        # atomic write: 임시 파일 후 mv → 반쪽 XML 로 덮어쓰지 않음
        local tmp; tmp="$(TMPDIR="$(dirname "${FASTDDS_XML}")" mktemp)"
        cat > "${tmp}" <<EOF
<?xml version="1.0" encoding="UTF-8" ?>
<!-- net_loadtest 폐쇄망 whitelist. Fast DDS 2.x (Humble/Jazzy) 대상.
     Fast DDS 3.x 는 interfaceWhiteList → interfaces/allowlist 로 개명됨.
     interfaceWhiteList 는 '로컬' 인터페이스만 필터 → 각 호스트는 자기 IP(+127.0.0.1) 만 매칭,
     동일 파일을 5대 전부에 배포 가능. useBuiltinTransports=false 로 whitelisted UDP 만 사용
     (타 NIC 차단). 127.0.0.1 = 같은 호스트 노드/데몬 통신 보존용.
     setup-closed-net.sh 관리 — 수동 편집 금지. -->
<dds xmlns="http://www.eprosima.com/XMLSchemas/fastRTPS_Profiles">
  <profiles>
    <transport_descriptors>
      <transport_descriptor>
        <transport_id>closed_net_udp</transport_id>
        <type>UDPv4</type>
        <interfaceWhiteList>
${wl}        </interfaceWhiteList>
      </transport_descriptor>
    </transport_descriptors>

    <participant profile_name="closed_net" is_default_profile="true">
      <rtps>
        <userTransports>
          <transport_id>closed_net_udp</transport_id>
        </userTransports>
        <useBuiltinTransports>false</useBuiltinTransports>
      </rtps>
    </participant>
  </profiles>
</dds>
EOF
        mv "${tmp}" "${FASTDDS_XML}"
        command -v xmllint >/dev/null && xmllint --noout "${FASTDDS_XML}" && echo "[dds] XML well-formed OK"
    fi

    # ~/.bashrc 관리 블록 (멱등: 마커 블록 제거 후 재기록)
    local bashrc="${HOME}/.bashrc"
    echo "[dds] ~/.bashrc 관리 블록 갱신 (RMW_IMPLEMENTATION / FASTRTPS_DEFAULT_PROFILES_FILE)"
    if ((!DRY)); then
        [[ -f "${bashrc}" ]] && sed -i "/${BEGIN_MARK}/,/${END_MARK}/d" "${bashrc}"
        {
            echo "${BEGIN_MARK}"
            echo "# TP-Link 폐쇄망 FastDDS whitelist (setup-closed-net.sh 관리 — 수동 편집 금지)"
            echo "# FastDDS 는 ROS2 Humble 기본 RMW 지만, 이 호스트가 CycloneDDS 로 override 돼 있을 수"
            echo "# 있어 명시적으로 고정 (profiles 파일은 FastDDS 만 읽음). 기존 cyclonedds 블록보다 뒤 → 우선."
            echo "export RMW_IMPLEMENTATION=rmw_fastrtps_cpp"
            echo "export FASTRTPS_DEFAULT_PROFILES_FILE=\"${FASTDDS_XML}\""
            echo "export FASTDDS_DEFAULT_PROFILES_FILE=\"${FASTDDS_XML}\"  # Fast DDS 3.x 이름"
            echo "${END_MARK}"
        } >> "${bashrc}"
    fi
    echo "[dds] 완료. 새 터미널 또는 'source ~/.bashrc' 후 적용."
}

# --- 실행 --------------------------------------------------------------------
((DO_IP))  && setup_ip
((DO_DDS)) && setup_dds
echo "== 완료 =="
