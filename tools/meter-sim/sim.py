#!/usr/bin/env python3
"""GridRight virtual smart meter simulator.

Pushes small dummy solar readings to the GridRight API and serves a live
web dashboard at http://localhost:7777 (auto-opens in your browser).

Usage
-----
  python sim.py --token gr_meter_<token> --meter-id METER-VSIM-001

  Or set env vars:
    GRIDRIGHT_DEVICE_TOKEN=gr_meter_...
    GRIDRIGHT_METER_ID=METER-VSIM-001
    python sim.py

Options
-------
  --token      Device token shown once after binding
  --meter-id   Meter ID shown in the dashboard
  --api        API base URL (default: https://gridright-api.onrender.com)
  --interval   Seconds between readings (default: 60)
  --port       Local dashboard port (default: 7777)
  --once       Push one reading and exit (no web server)
  --no-browser Don't auto-open the browser
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import os
import random
import sys
import threading
import time
import urllib.request
import urllib.error
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

API_DEFAULT = "https://gridright-api.onrender.com"
MAX_HISTORY = 48
GEN_BASE_KWH  = 0.15
CONS_BASE_KWH = 0.06

_lock    = threading.Lock()
_history: collections.deque = collections.deque(maxlen=MAX_HISTORY)
_sse_clients: list = []

# ── HTML dashboard ────────────────────────────────────────────────────────────
_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>GridRight Virtual Meter</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:system-ui,sans-serif;background:#09090b;color:#f4f4f5;min-height:100vh;padding:24px}
h1{font-size:1.25rem;font-weight:600;margin-bottom:4px}
.sub{font-size:.8rem;color:#71717a;margin-bottom:24px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-bottom:24px}
.card{background:#18181b;border:1px solid #27272a;border-radius:8px;padding:16px}
.card .label{font-size:.75rem;color:#71717a;margin-bottom:4px}
.card .val{font-size:1.5rem;font-weight:600;font-variant-numeric:tabular-nums}
.unit{font-size:.75rem;color:#71717a;margin-left:4px}
.green{color:#4ade80}.amber{color:#fbbf24}.blue{color:#60a5fa}
.chart-wrap{background:#18181b;border:1px solid #27272a;border-radius:8px;padding:16px;margin-bottom:24px}
.chart-wrap h2{font-size:.875rem;font-weight:500;margin-bottom:12px;color:#a1a1aa}
svg.chart{width:100%;height:80px;display:block}
.legend{display:flex;gap:16px;font-size:.75rem;color:#71717a;margin-top:8px}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px}
.table-wrap{background:#18181b;border:1px solid #27272a;border-radius:8px;padding:16px;max-height:260px;overflow-y:auto}
.table-wrap h2{font-size:.875rem;font-weight:500;margin-bottom:12px;color:#a1a1aa}
table{width:100%;border-collapse:collapse;font-size:.8rem}
th{text-align:left;color:#71717a;padding-bottom:8px;font-weight:500}
td{padding:6px 0;border-top:1px solid #27272a;font-variant-numeric:tabular-nums}
.badge{display:inline-block;padding:2px 8px;border-radius:4px;font-size:.7rem;font-weight:500}
.ok{background:#14532d;color:#4ade80}.err{background:#450a0a;color:#f87171}
.status-bar{font-size:.75rem;color:#71717a;margin-bottom:16px}
#dot-live{display:inline-block;width:8px;height:8px;border-radius:50%;background:#4ade80;margin-right:6px;animation:pulse 2s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
</style></head>
<body>
<h1>GridRight Virtual Meter</h1>
<div class="sub" id="meter-id">Connecting…</div>
<div class="status-bar"><span id="dot-live"></span><span id="status-txt">Waiting for first reading…</span></div>
<div class="grid">
  <div class="card"><div class="label">Generation</div><div class="val green" id="gen">—</div><span class="unit">kWh</span></div>
  <div class="card"><div class="label">Consumption</div><div class="val blue" id="cons">—</div><span class="unit">kWh</span></div>
  <div class="card"><div class="label">Grid export</div><div class="val amber" id="exp">—</div><span class="unit">kWh</span></div>
  <div class="card"><div class="label">Readings sent</div><div class="val" id="count">0</div></div>
</div>
<div class="chart-wrap">
  <h2>Recent readings</h2>
  <svg class="chart" id="chart" viewBox="0 0 560 80" preserveAspectRatio="none"></svg>
  <div class="legend">
    <span><span class="dot" style="background:#fbbf24"></span>Generation</span>
    <span><span class="dot" style="background:#4ade80"></span>Grid export</span>
  </div>
</div>
<div class="table-wrap">
  <h2>Reading log</h2>
  <table><thead><tr><th>Time</th><th>Gen kWh</th><th>Cons kWh</th><th>Export kWh</th><th>API</th></tr></thead>
  <tbody id="tbody"></tbody></table>
</div>
<script>
const genEl=document.getElementById('gen'),consEl=document.getElementById('cons'),
  expEl=document.getElementById('exp'),countEl=document.getElementById('count'),
  statusEl=document.getElementById('status-txt'),meterEl=document.getElementById('meter-id'),
  tbody=document.getElementById('tbody'),chart=document.getElementById('chart');
let history=[],count=0;
function fmt(v){return v.toFixed(4)}
function drawChart(){
  if(history.length<2){chart.innerHTML='';return}
  const W=560,H=80,pad=4;
  const maxG=Math.max(0.001,...history.map(r=>r.gen));
  const x=i=>(i/(history.length-1))*W;
  const y=v=>H-pad-(v/maxG)*(H-2*pad);
  const line=(pick,col)=>{
    const d=history.map((r,i)=>`${i===0?'M':'L'}${x(i).toFixed(1)},${y(pick(r)).toFixed(1)}`).join(' ');
    return `<path d="${d}" fill="none" stroke="${col}" stroke-width="1.5"/>`;
  };
  chart.innerHTML=line(r=>r.gen,'#fbbf24')+line(r=>r.exp,'#4ade80');
}
function onReading(d){
  count++;
  genEl.textContent=fmt(d.gen);consEl.textContent=fmt(d.cons);expEl.textContent=fmt(d.exp);
  countEl.textContent=count;
  meterEl.textContent='Meter: '+d.meter_id;
  statusEl.textContent='Last reading: '+new Date(d.ts).toLocaleTimeString();
  history.push(d);if(history.length>48)history.shift();
  drawChart();
  const tr=document.createElement('tr');
  const badge=d.ok?'<span class="badge ok">201</span>':'<span class="badge err">'+d.http+'</span>';
  tr.innerHTML=`<td>${new Date(d.ts).toLocaleTimeString()}</td><td>${fmt(d.gen)}</td><td>${fmt(d.cons)}</td><td>${fmt(d.exp)}</td><td>${badge}</td>`;
  tbody.prepend(tr);
  if(tbody.children.length>100)tbody.lastChild.remove();
}
const es=new EventSource('/events');
es.onmessage=e=>{try{onReading(JSON.parse(e.data))}catch(_){}};
es.onerror=()=>{statusEl.textContent='Reconnecting…'};
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
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(_HTML.encode())))
            self.end_headers()
            self.wfile.write(_HTML.encode())


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
        t = threading.Thread(target=_run_server, args=(args.port,), daemon=True)
        t.start()
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
