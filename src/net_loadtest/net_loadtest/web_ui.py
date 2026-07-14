# Self-contained dashboard page (no external JS/CSS/fonts -> works on the closed
# network, offline). Dark-first developer-tool aesthetic (ref: awesome-design-md).
# Colors are the validated dataviz palette (light+dark). Charts are hand-drawn on
# canvas -- no chart library to bundle.
PAGE = r"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Network Load Test — Live</title>
<style>
:root{
  color-scheme: dark light;
  --page:#0d0d0d; --surface:#1a1a19; --surface-2:#212120;
  --text:#fff; --text-2:#c3c2b7; --muted:#898781;
  --grid:#2c2c2a; --axis:#383835; --border:rgba(255,255,255,.10);
  --s1:#3987e5; --s2:#199e70; --s3:#c98500; --s6:#e66767;
  --good:#0ca30c; --warn:#fab219; --crit:#d03b3b;
}
@media (prefers-color-scheme: light){:root{
  --page:#f9f9f7; --surface:#fcfcfb; --surface-2:#f2f2ef;
  --text:#0b0b0b; --text-2:#52514e; --muted:#898781;
  --grid:#e1e0d9; --axis:#c3c2b7; --border:rgba(11,11,11,.10);
  --s1:#2a78d6; --s2:#1baf7a; --s3:#eda100; --s6:#e34948;
}}
*{box-sizing:border-box}
body{margin:0;background:var(--page);color:var(--text);
  font-family:system-ui,-apple-system,"Segoe UI",sans-serif;font-size:14px}
.wrap{max-width:1180px;margin:0 auto;padding:20px 18px 40px}
header{display:flex;align-items:center;gap:14px;margin-bottom:18px;flex-wrap:wrap}
h1{font-size:16px;font-weight:600;margin:0;letter-spacing:.2px}
.sub{color:var(--muted);font-size:12px}
.badge{margin-left:auto;display:flex;align-items:center;gap:8px;font-size:12px;color:var(--text-2)}
.dot{width:9px;height:9px;border-radius:50%;background:var(--crit);transition:background .3s}
.dot.on{background:var(--good)}
.step{padding:3px 9px;border:1px solid var(--border);border-radius:6px;
  background:var(--surface);color:var(--text-2);font-variant-numeric:tabular-nums}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:16px}
.tile{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:12px 14px}
.tile .k{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.5px}
.tile .v{font-size:26px;font-weight:600;font-variant-numeric:tabular-nums;margin-top:4px;line-height:1.1}
.tile .u{color:var(--muted);font-size:12px;font-weight:400}
.tile.good .v{color:var(--good)} .tile.warning .v{color:var(--warn)} .tile.critical .v{color:var(--crit)}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:14px}
@media(max-width:820px){.grid2{grid-template-columns:1fr}}
.card{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:14px 16px 10px}
.card h2{font-size:13px;font-weight:600;margin:0 0 2px}
.legend{display:flex;gap:14px;flex-wrap:wrap;margin:6px 0 4px;font-size:12px;color:var(--text-2)}
.legend span{display:inline-flex;align-items:center;gap:6px}
.legend i{width:11px;height:2.5px;border-radius:2px;display:inline-block}
canvas{width:100%;height:210px;display:block}
.ports{display:flex;flex-direction:column;gap:8px;margin-top:6px}
.port{display:grid;grid-template-columns:120px 1fr auto;align-items:center;gap:10px;font-size:12px}
.port .nm{color:var(--text-2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-variant-numeric:tabular-nums}
.bar{height:14px;background:var(--surface-2);border-radius:4px;overflow:hidden;position:relative}
.bar>i{position:absolute;left:0;top:0;bottom:0;background:var(--s1);border-radius:4px;transition:width .4s}
.port .val{color:var(--text);font-variant-numeric:tabular-nums;min-width:78px;text-align:right}
.foot{color:var(--muted);font-size:11px;margin-top:18px}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div>
      <h1>Network Load Test <span class="sub">— 실시간 모니터링</span></h1>
      <div class="sub" id="cap">스위치 집계 · 포트별 bps · 지연 · 손실</div>
    </div>
    <div class="badge">
      <span class="step" id="step">step —</span>
      <span class="dot" id="dot"></span><span id="conn">연결 대기</span>
    </div>
  </header>

  <div class="tiles" id="tiles"></div>

  <div class="grid2">
    <div class="card">
      <h2>스위치 throughput</h2>
      <div class="legend">
        <span><i style="background:var(--s1)"></i>ingress</span>
        <span><i style="background:var(--s2)"></i>egress(delivered)</span>
      </div>
      <canvas id="thr"></canvas>
    </div>
    <div class="card">
      <h2>지연 latency (one-way)</h2>
      <div class="legend">
        <span><i style="background:var(--s1)"></i>p50</span>
        <span><i style="background:var(--s3)"></i>p95</span>
        <span><i style="background:var(--s6)"></i>max</span>
      </div>
      <canvas id="lat"></canvas>
    </div>
  </div>

  <div class="card" style="margin-top:14px">
    <h2>포트별 bps <span class="sub" id="portsub"></span></h2>
    <div class="ports" id="ports"></div>
  </div>

  <div class="foot" id="foot">데이터 대기 중… 코디네이터에서 aggregator + ramp_controller 가 도는지 확인.</div>
</div>

<script>
const CSS = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const MAXPTS = 120;                 // rolling window (~2 min @ 1 Hz)
const hist = [];                    // array of payloads
const fmt = (x,d=1)=> (x==null||isNaN(x))?'—':Number(x).toFixed(d);

// ---- stat tiles ----
const TILES = [
  {k:'ingress', u:'Mbps', get:d=>fmt(d.ingress), st:d=>null},
  {k:'egress',  u:'Mbps', get:d=>fmt(d.egress),  st:d=>null},
  {k:'loss',    u:'%',    get:d=>fmt(d.loss_pct,2), st:d=>d.status&&d.status.loss},
  {k:'p95 lat', u:'ms',   get:d=>fmt(d.p95,2),   st:d=>d.status&&d.status.latency},
  {k:'queueing',u:'ms',   get:d=>fmt(d.queueing_p95,2), st:d=>null},
  {k:'gap loss',u:'pkts', get:d=>d.gap_loss==null?'—':d.gap_loss, st:d=>d.gap_loss>0?'warning':'good'},
  {k:'max port',u:'Mbps', get:d=>fmt(d.max_port_mbps), st:d=>null},
];
function renderTiles(d){
  const box=document.getElementById('tiles');
  box.innerHTML = TILES.map(t=>{
    const st=t.st(d)||'';
    return `<div class="tile ${st}"><div class="k">${t.k}</div>
      <div class="v">${t.get(d)} <span class="u">${t.u}</span></div></div>`;
  }).join('');
}

// ---- canvas line chart with hover crosshair ----
function lineChart(cv, series, unit){
  const dpr=window.devicePixelRatio||1, W=cv.clientWidth, H=cv.clientHeight;
  cv.width=W*dpr; cv.height=H*dpr;
  const ctx=cv.getContext('2d'); ctx.scale(dpr,dpr);
  ctx.clearRect(0,0,W,H);
  const padL=46,padR=14,padT=10,padB=20, iw=W-padL-padR, ih=H-padT-padB;
  const n=hist.length;
  let mx=0; series.forEach(s=>hist.forEach(d=>{const v=s.get(d); if(v!=null&&v>mx)mx=v;}));
  mx = mx<=0?1:mx*1.15;
  const X=i=> padL + (n<=1?0:iw*i/(n-1));
  const Y=v=> padT + ih - ih*Math.min(v,mx)/mx;
  // gridlines + y labels
  ctx.font='11px system-ui'; ctx.textBaseline='middle';
  ctx.strokeStyle=CSS('--grid'); ctx.fillStyle=CSS('--muted'); ctx.lineWidth=1;
  for(let g=0;g<=4;g++){const y=padT+ih*g/4, val=mx*(1-g/4);
    ctx.beginPath();ctx.moveTo(padL,y+.5);ctx.lineTo(W-padR,y+.5);ctx.stroke();
    ctx.fillText(val>=100?val.toFixed(0):val.toFixed(1), 4, y);}
  // series
  series.forEach(s=>{
    ctx.strokeStyle=CSS(s.color); ctx.lineWidth=2; ctx.beginPath();
    let started=false;
    hist.forEach((d,i)=>{const v=s.get(d); if(v==null)return;
      const x=X(i),y=Y(v); if(!started){ctx.moveTo(x,y);started=true;}else ctx.lineTo(x,y);});
    ctx.stroke();
    // last-value dot + direct label
    for(let i=n-1;i>=0;i--){const v=s.get(hist[i]); if(v!=null){
      const x=X(i),y=Y(v); ctx.fillStyle=CSS(s.color);
      ctx.beginPath();ctx.arc(x,y,3,0,7);ctx.fill();
      ctx.textAlign='right';ctx.fillText(fmt(v, mx<10?2:1), Math.min(x,W-padR), y-9);
      ctx.textAlign='left'; break;}}
  });
  cv._meta={X,Y,padL,padR,padT,padB,iw,ih,n,unit,series};
}
function hover(cv,mxpos){
  const m=cv._meta; if(!m||!m.n)return; const box=cv._tip||(cv._tip=mkTip(cv));
  if(mxpos==null){box.style.display='none';drawAll();return;}
  const rel=Math.max(0,Math.min(m.n-1, Math.round((mxpos-m.padL)/(m.iw||1)*(m.n-1))));
  drawAll();
  const ctx=cv.getContext('2d'), x=m.padL+(m.n<=1?0:m.iw*rel/(m.n-1));
  ctx.save();ctx.scale(window.devicePixelRatio||1,window.devicePixelRatio||1);
  ctx.strokeStyle=CSS('--axis');ctx.lineWidth=1;ctx.beginPath();
  ctx.moveTo(x,m.padT);ctx.lineTo(x,m.padT+m.ih);ctx.stroke();ctx.restore();
  const d=hist[rel];
  box.innerHTML = m.series.map(s=>`<span style="color:${CSS(s.color)}">●</span> ${s.label}: `
      +`<b>${fmt(s.get(d), 2)}</b> ${m.unit}`).join('<br>');
  box.style.display='block';
  const r=cv.getBoundingClientRect();
  box.style.left=Math.min(x+10, cv.clientWidth-140)+'px'; box.style.top='12px';
}
function mkTip(cv){const t=document.createElement('div');
  t.style.cssText='position:absolute;pointer-events:none;background:var(--surface-2);'
   +'border:1px solid var(--border);border-radius:7px;padding:6px 9px;font-size:11px;'
   +'font-variant-numeric:tabular-nums;display:none;z-index:5;white-space:nowrap';
  cv.parentElement.style.position='relative'; cv.parentElement.appendChild(t); return t;}

const THR=[{label:'ingress',color:'--s1',get:d=>d.ingress},
           {label:'egress', color:'--s2',get:d=>d.egress}];
const LAT=[{label:'p50',color:'--s1',get:d=>d.p50},
           {label:'p95',color:'--s3',get:d=>d.p95},
           {label:'max',color:'--s6',get:d=>d.max}];
function drawAll(){
  lineChart(document.getElementById('thr'), THR, 'Mbps');
  lineChart(document.getElementById('lat'), LAT, 'ms');
}
['thr','lat'].forEach(id=>{const cv=document.getElementById(id);
  cv.addEventListener('mousemove',e=>hover(cv, e.clientX-cv.getBoundingClientRect().left));
  cv.addEventListener('mouseleave',()=>hover(cv,null));});

// ---- per-port bars ----
function renderPorts(d){
  const box=document.getElementById('ports'); const ps=d.port_list||[];
  document.getElementById('portsub').textContent = ps.length? `(${ps.length} ports)`:'';
  if(!ps.length){box.innerHTML='<div class="sub">nic_reporter 데이터 없음</div>';return;}
  const mx=Math.max(1,...ps.map(p=>Math.max(p.rx,p.tx)));
  box.innerHTML = ps.map(p=>{const v=Math.max(p.rx,p.tx);
    return `<div class="port"><div class="nm" title="${p.name}">${p.name}</div>
      <div class="bar"><i style="width:${(v/mx*100).toFixed(1)}%"></i></div>
      <div class="val">${fmt(v)} Mbps</div></div>`;}).join('');
}

function update(d){
  hist.push(d); while(hist.length>MAXPTS)hist.shift();
  document.getElementById('step').textContent =
    `step ${d.step} · ${fmt(d.target_mbps,0)} Mbps/src`;
  renderTiles(d); renderPorts(d); drawAll();
  document.getElementById('foot').textContent =
    `업데이트 ${new Date().toLocaleTimeString()} · window ${hist.length}/${MAXPTS} · 손실 시작·큐잉 급증 지점 = 스위치 감당 한계`;
}

// ---- SSE ----
function connect(){
  const es=new EventSource('/events');
  const dot=document.getElementById('dot'), conn=document.getElementById('conn');
  es.onopen =()=>{dot.classList.add('on'); conn.textContent='연결됨';};
  es.onerror=()=>{dot.classList.remove('on'); conn.textContent='재연결 중…';};
  es.onmessage=e=>{ if(!e.data)return; try{update(JSON.parse(e.data));}catch(_){} };
}
window.addEventListener('resize',drawAll);
connect();
</script>
</body>
</html>
"""
