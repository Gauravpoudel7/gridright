#!/usr/bin/env python3
"""GridRight virtual smart meter simulator.

Pushes small dummy solar readings to the GridRight API and serves a live
3D meter dashboard at http://localhost:7777 (auto-opens in your browser).

Usage:  python sim.py --token gr_meter_<token> --meter-id METER-VSIM-001
        GRIDRIGHT_DEVICE_TOKEN=... GRIDRIGHT_METER_ID=... python sim.py
"""
from __future__ import annotations
import argparse, collections, json, math, os, random, sys
import threading, time, urllib.request, urllib.error, webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

API_DEFAULT   = "https://gridright-api.onrender.com"
MAX_HISTORY   = 48
GEN_BASE_KWH  = 0.15
CONS_BASE_KWH = 0.06

_lock         = threading.Lock()
_history: collections.deque = collections.deque(maxlen=MAX_HISTORY)
_sse_clients: list = []

_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>GridRight Smart Meter</title>
<link href="https://fonts.googleapis.com/css2?family=Share+Tech+Mono&display=swap" rel="stylesheet">
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:radial-gradient(ellipse at center,#1a1a2e 0%,#0a0a0f 100%);
  min-height:100vh;display:flex;flex-direction:column;align-items:center;
  justify-content:flex-start;padding:30px 16px;font-family:'Share Tech Mono',monospace;
  color:#e0e0e0;overflow-x:hidden}
/* ── meter housing ── */
.meter-housing{
  width:100%;max-width:480px;
  background:linear-gradient(160deg,#2a2a2a 0%,#1a1a1a 40%,#111 100%);
  border-radius:16px;
  border:2px solid #444;
  box-shadow:
    0 0 0 1px #666 inset,
    0 4px 8px rgba(0,0,0,.8),
    0 20px 60px rgba(0,0,0,.9),
    0 0 40px rgba(0,200,100,.04);
  padding:24px;
  perspective:800px;
  position:relative;
  margin-bottom:20px}
.meter-housing::before{
  content:'';position:absolute;inset:0;border-radius:16px;
  background:linear-gradient(135deg,rgba(255,255,255,.06) 0%,transparent 50%);
  pointer-events:none}
/* ── brand plate ── */
.brand{display:flex;align-items:center;justify-content:space-between;margin-bottom:18px}
.brand-name{font-size:.65rem;letter-spacing:.2em;color:#888;text-transform:uppercase}
.brand-model{font-size:.6rem;color:#555;letter-spacing:.1em}
.status-led{width:10px;height:10px;border-radius:50%;
  background:#00ff88;
  box-shadow:0 0 6px #00ff88,0 0 12px #00ff88,0 0 24px rgba(0,255,136,.4);
  animation:ledpulse 2s ease-in-out infinite}
@keyframes ledpulse{0%,100%{opacity:1;box-shadow:0 0 6px #00ff88,0 0 12px #00ff88}
  50%{opacity:.5;box-shadow:0 0 3px #00ff88}}
/* ── LCD display ── */
.lcd-panel{
  background:#0a1a0a;
  border:1px solid #1a3a1a;
  border-radius:8px;
  padding:16px 20px;
  margin-bottom:20px;
  position:relative;
  overflow:hidden;
  box-shadow:0 0 20px rgba(0,255,100,.08) inset,0 2px 4px rgba(0,0,0,.8)}
.lcd-panel::after{
  content:'';position:absolute;inset:0;
  background:repeating-linear-gradient(0deg,transparent,transparent 2px,rgba(0,0,0,.08) 2px,rgba(0,0,0,.08) 4px);
  pointer-events:none;border-radius:8px}
.lcd-label{font-size:.55rem;letter-spacing:.15em;color:#2a6a2a;text-transform:uppercase;margin-bottom:4px}
.lcd-value{font-size:2.8rem;color:#00ff88;letter-spacing:.05em;
  text-shadow:0 0 10px rgba(0,255,136,.8),0 0 20px rgba(0,255,136,.4);
  line-height:1;font-variant-numeric:tabular-nums}
.lcd-unit{font-size:.75rem;color:#1a8a1a;margin-left:6px;vertical-align:middle}
.lcd-sub{display:flex;gap:20px;margin-top:10px;padding-top:10px;border-top:1px solid #0f2f0f}
.lcd-sub-item .lcd-label{font-size:.5rem}
.lcd-sub-item .lcd-value{font-size:1.1rem}
/* ── arc gauges ── */
.gauges{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:20px}
.gauge-wrap{display:flex;flex-direction:column;align-items:center}
.gauge-label{font-size:.5rem;letter-spacing:.12em;color:#666;text-transform:uppercase;margin-top:6px}
.gauge-val{font-size:.75rem;color:#aaa;margin-top:2px;font-variant-numeric:tabular-nums}
/* ── chart ── */
.chart-panel{background:#0d0d0d;border:1px solid #222;border-radius:8px;padding:14px;margin-bottom:20px}
.chart-title{font-size:.55rem;letter-spacing:.15em;color:#555;text-transform:uppercase;margin-bottom:10px}
svg.chart{width:100%;height:64px;display:block}
.legend{display:flex;gap:16px;margin-top:8px}
.legend span{font-size:.55rem;color:#555;display:flex;align-items:center;gap:5px}
.legend-dot{width:6px;height:6px;border-radius:50%;display:inline-block}
/* ── log table ── */
.log-panel{background:#0d0d0d;border:1px solid #222;border-radius:8px;padding:14px;
  max-height:220px;overflow-y:auto;width:100%;max-width:480px}
.log-title{font-size:.55rem;letter-spacing:.15em;color:#555;text-transform:uppercase;margin-bottom:10px}
table{width:100%;border-collapse:collapse;font-size:.65rem}
th{color:#444;padding-bottom:6px;text-align:left;font-weight:400;letter-spacing:.08em}
td{padding:4px 0;border-top:1px solid #161616;color:#777;font-variant-numeric:tabular-nums}
.badge{padding:1px 6px;border-radius:3px;font-size:.6rem}
.ok{background:#0a2a0a;color:#00cc66;border:1px solid #0f4a0f}
.err{background:#2a0a0a;color:#cc3333;border:1px solid #4a0f0f}
/* ── meter id strip ── */
.meter-strip{
  display:flex;align-items:center;justify-content:space-between;
  background:#0a0a0a;border:1px solid #1a1a1a;border-radius:6px;
  padding:8px 12px;margin-bottom:20px;font-size:.6rem}
.meter-id-val{color:#444;letter-spacing:.1em}
.meter-id-val span{color:#666}
.conn-status{font-size:.55rem;color:#2a6a2a;letter-spacing:.1em}
/* ── scrollbar ── */
::-webkit-scrollbar{width:4px}
::-webkit-scrollbar-track{background:#0a0a0a}
::-webkit-scrollbar-thumb{background:#222;border-radius:2px}
</style></head>
<body>
<div class="meter-housing">
  <div class="brand">
    <div><div class="brand-name">GridRight Energy</div><div class="brand-model">VSM-001 &nbsp;|&nbsp; Smart Meter</div></div>
    <div class="status-led" id="led"></div>
  </div>
  <div class="meter-strip">
    <div><span class="meter-id-val">ID: <span id="mid">—</span></span></div>
    <div class="conn-status" id="conn-status">CONNECTING</div>
  </div>
  <div class="lcd-panel">
    <div class="lcd-label">Grid Export &mdash; Current Reading</div>
    <div><span class="lcd-value" id="exp">0.0000</span><span class="lcd-unit">kWh</span></div>
    <div class="lcd-sub">
      <div class="lcd-sub-item"><div class="lcd-label">Generation</div>
        <div><span class="lcd-value" id="gen">0.0000</span><span class="lcd-unit" style="font-size:.6rem">kWh</span></div></div>
      <div class="lcd-sub-item"><div class="lcd-label">Consumption</div>
        <div><span class="lcd-value" id="cons">0.0000</span><span class="lcd-unit" style="font-size:.6rem">kWh</span></div></div>
      <div class="lcd-sub-item"><div class="lcd-label">Readings</div>
        <div><span class="lcd-value" id="count">0</span></div></div>
    </div>
  </div>
  <div class="gauges">
    <div class="gauge-wrap"><svg width="100" height="60" viewBox="0 0 100 60"><defs>
      <linearGradient id="gg" x1="0%" y1="0%" x2="100%" y2="0%">
        <stop offset="0%" style="stop-color:#004400"/><stop offset="100%" style="stop-color:#00ff88"/></linearGradient></defs>
      <path d="M10,55 A45,45 0 0,1 90,55" fill="none" stroke="#111" stroke-width="8" stroke-linecap="round"/>
      <path id="arc-gen" d="M10,55 A45,45 0 0,1 90,55" fill="none" stroke="url(#gg)" stroke-width="8" stroke-linecap="round"
        stroke-dasharray="141" stroke-dashoffset="141" style="transition:stroke-dashoffset .8s ease"/>
      <text x="50" y="42" text-anchor="middle" font-size="9" fill="#00ff88" font-family="Share Tech Mono,monospace" id="arc-gen-txt">0%</text>
    </svg><div class="gauge-label">Generation</div><div class="gauge-val" id="gv">—</div></div>
    <div class="gauge-wrap"><svg width="100" height="60" viewBox="0 0 100 60"><defs>
      <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="0%">
        <stop offset="0%" style="stop-color:#000044"/><stop offset="100%" style="stop-color:#4488ff"/></linearGradient></defs>
      <path d="M10,55 A45,45 0 0,1 90,55" fill="none" stroke="#111" stroke-width="8" stroke-linecap="round"/>
      <path id="arc-cons" d="M10,55 A45,45 0 0,1 90,55" fill="none" stroke="url(#bg)" stroke-width="8" stroke-linecap="round"
        stroke-dasharray="141" stroke-dashoffset="141" style="transition:stroke-dashoffset .8s ease"/>
      <text x="50" y="42" text-anchor="middle" font-size="9" fill="#4488ff" font-family="Share Tech Mono,monospace" id="arc-cons-txt">0%</text>
    </svg><div class="gauge-label">Consumption</div><div class="gauge-val" id="cv">—</div></div>
    <div class="gauge-wrap"><svg width="100" height="60" viewBox="0 0 100 60"><defs>
      <linearGradient id="ag" x1="0%" y1="0%" x2="100%" y2="0%">
        <stop offset="0%" style="stop-color:#442200"/><stop offset="100%" style="stop-color:#ffaa00"/></linearGradient></defs>
      <path d="M10,55 A45,45 0 0,1 90,55" fill="none" stroke="#111" stroke-width="8" stroke-linecap="round"/>
      <path id="arc-exp" d="M10,55 A45,45 0 0,1 90,55" fill="none" stroke="url(#ag)" stroke-width="8" stroke-linecap="round"
        stroke-dasharray="141" stroke-dashoffset="141" style="transition:stroke-dashoffset .8s ease"/>
      <text x="50" y="42" text-anchor="middle" font-size="9" fill="#ffaa00" font-family="Share Tech Mono,monospace" id="arc-exp-txt">0%</text>
    </svg><div class="gauge-label">Grid Export</div><div class="gauge-val" id="ev">—</div></div>
  </div>
  <div class="chart-panel">
    <div class="chart-title">Waveform &mdash; Last 48 readings</div>
    <svg class="chart" id="chart" viewBox="0 0 560 64" preserveAspectRatio="none"></svg>
    <div class="legend">
      <span><span class="legend-dot" style="background:#00ff88"></span>Generation</span>
      <span><span class="legend-dot" style="background:#ffaa00"></span>Grid export</span>
      <span><span class="legend-dot" style="background:#4488ff"></span>Consumption</span>
    </div>
  </div>
</div>
<div class="log-panel">
  <div class="log-title">Transmission log</div>
  <table><thead><tr><th>TIME</th><th>GEN</th><th>CONS</th><th>EXPORT</th><th>TX</th></tr></thead>
  <tbody id="tbody"></tbody></table>
</div>
<script>
const $=id=>document.getElementById(id);
let history=[],count=0,maxG=0.35;
function fmt(v){return v.toFixed(4)}
function setArc(id,val,max){
  const pct=Math.min(1,val/max),offset=141*(1-pct);
  $(id).style.strokeDashoffset=offset;
  $(id+'-txt').textContent=Math.round(pct*100)+'%';
}
function drawChart(){
  if(history.length<2){$('chart').innerHTML='';return}
  const W=560,H=64,pad=4;
  const mG=Math.max(0.001,...history.map(r=>r.gen));
  const x=i=>(i/(history.length-1))*W;
  const y=(v,m)=>H-pad-(v/m)*(H-2*pad);
  const line=(pick,col,m)=>{
    const d=history.map((r,i)=>`${i===0?'M':'L'}${x(i).toFixed(1)},${y(pick(r),m).toFixed(1)}`).join(' ');
    return `<path d="${d}" fill="none" stroke="${col}" stroke-width="1.5" opacity=".9"/>`;
  };
  $('chart').innerHTML=
    line(r=>r.gen,'#00ff88',mG)+
    line(r=>r.exp,'#ffaa00',mG)+
    line(r=>r.cons,'#4488ff',mG);
}
function onReading(d){
  count++;
  $('exp').textContent=fmt(d.exp);
  $('gen').textContent=fmt(d.gen);
  $('cons').textContent=fmt(d.cons);
  $('count').textContent=count;
  $('mid').textContent=d.meter_id;
  $('conn-status').textContent=d.ok?'LIVE':'ERR';
  $('conn-status').style.color=d.ok?'#00cc66':'#cc3333';
  $('gv').textContent=fmt(d.gen)+' kWh';
  $('cv').textContent=fmt(d.cons)+' kWh';
  $('ev').textContent=fmt(d.exp)+' kWh';
  const m=Math.max(maxG,d.gen,d.cons,d.exp);
  setArc('arc-gen',d.gen,m);
  setArc('arc-cons',d.cons,m);
  setArc('arc-exp',d.exp,m);
  history.push(d);if(history.length>48)history.shift();
  drawChart();
  const tr=document.createElement('tr');
  const badge=d.ok?'<span class="badge ok">ACK</span>':'<span class="badge err">'+d.http+'</span>';
  tr.innerHTML=`<td>${new Date(d.ts).toLocaleTimeString()}</td><td>${fmt(d.gen)}</td><td>${fmt(d.cons)}</td><td>${fmt(d.exp)}</td><td>${badge}</td>`;
  $('tbody').prepend(tr);
  if($('tbody').children.length>100)$('tbody').lastChild.remove();
}
const es=new EventSource('/events');
es.onmessage=e=>{try{onReading(JSON.parse(e.data))}catch(_){}};
es.onerror=()=>{$('conn-status').textContent='RECONNECTING';$('conn-status').style.color='#886600'};
</script></body></html>"""


# ── helpers ───────────────────────────────────────────────────────────────────

def _solar_factor(t: datetime) -> float:
    hour = t.hour + t.minute / 60.0
    if hour < 6 or hour > 20:
        return 0.0
    return max(0.0, math.sin(math.pi * (hour - 6) / 14.0))


def make_reading(meter_id: str) -> dict:
    now = datetime.now(timezone.utc)
    factor = _solar_factor(now)
    noise = lambda: random.uniform(0.85, 1.15)
    generation  = round(GEN_BASE_KWH  * factor * noise(), 4)
    consumption = round(CONS_BASE_KWH * noise(), 4)
    grid_export = round(max(0.0, generation - consumption) * random.uniform(0.7, 0.95), 4)
    return {
        "meter_device_id": meter_id,
        "reading_at": now.isoformat(),
        "generation_kwh": generation,
        "consumption_kwh": consumption,
        "grid_export_kwh": grid_export,
    }


def push(api: str, token: str, reading: dict) -> tuple[int, str]:
    body = json.dumps(reading).encode()
    req = urllib.request.Request(
        f"{api.rstrip('/')}/api/v1/meter-readings",
        data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()
    except Exception as exc:
        return 0, str(exc)


def _broadcast(event: dict) -> None:
    data = ("data: " + json.dumps(event) + "\n\n").encode()
    with _lock:
        dead = []
        for wfile in _sse_clients:
            try:
                wfile.write(data)
                wfile.flush()
            except Exception:
                dead.append(wfile)
        for w in dead:
            _sse_clients.remove(w)


# ── HTTP server ───────────────────────────────────────────────────────────────

class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        if self.path == "/events":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            with _lock:
                _sse_clients.append(self.wfile)
                hist = list(_history)
            for ev in hist:
                try:
                    self.wfile.write(("data: " + json.dumps(ev) + "\n\n").encode())
                    self.wfile.flush()
                except Exception:
                    return
            try:
                while True:
                    time.sleep(30)
            except Exception:
                pass
        else:
            html = _HTML.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)


def _run_server(port: int) -> None:
    HTTPServer(("127.0.0.1", port), _Handler).serve_forever()


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="GridRight virtual meter sim")
    parser.add_argument("--token",      default=os.getenv("GRIDRIGHT_DEVICE_TOKEN", ""))
    parser.add_argument("--meter-id",   default=os.getenv("GRIDRIGHT_METER_ID", "METER-VSIM-001"))
    parser.add_argument("--api",        default=os.getenv("GRIDRIGHT_API_URL", API_DEFAULT))
    parser.add_argument("--interval",   type=int, default=60)
    parser.add_argument("--port",       type=int, default=7777)
    parser.add_argument("--once",       action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    if not args.token:
        print("ERROR: provide --token or set GRIDRIGHT_DEVICE_TOKEN", file=sys.stderr)
        print("  Bind the meter in the seller dashboard (pairing code: VSIM-001),", file=sys.stderr)
        print("  copy the one-time device token, then re-run with --token <token>", file=sys.stderr)
        sys.exit(1)

    if not args.once:
        threading.Thread(target=_run_server, args=(args.port,), daemon=True).start()
        url = f"http://localhost:{args.port}"
        print(f"Dashboard      : {url}")
        if not args.no_browser:
            threading.Timer(1.0, webbrowser.open, args=(url,)).start()

    print(f"Virtual meter  : {args.meter_id}")
    print(f"API            : {args.api}")
    print(f"Interval       : {args.interval}s")
    print(f"Token          : {args.token[:16]}...")
    print()

    while True:
        reading = make_reading(args.meter_id)
        status, body = push(args.api, args.token, reading)
        ts = datetime.now().strftime("%H:%M:%S")
        ok = status == 201
        event = {
            "meter_id": args.meter_id,
            "ts": reading["reading_at"],
            "gen": reading["generation_kwh"],
            "cons": reading["consumption_kwh"],
            "exp": reading["grid_export_kwh"],
            "ok": ok,
            "http": status,
        }
        if not args.once:
            with _lock:
                _history.append(event)
            _broadcast(event)
        if ok:
            print(f"[{ts}] OK  gen={reading['generation_kwh']:.4f}  "
                  f"cons={reading['consumption_kwh']:.4f}  "
                  f"export={reading['grid_export_kwh']:.4f} kWh")
        else:
            print(f"[{ts}] ERR HTTP {status}: {body[:120]}")
        if args.once:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
