"""Claude Code Monitor - FastAPI Backend v2

PTY + WebSocket: real-time bidirectional terminal mirroring for Claude Code CLI.
Uses threading.Queue for reliable PTY-to-WebSocket data relay.
"""

import os
import subprocess
import asyncio
import json
import sys
import time
import threading
import queue
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse
import uvicorn

sys.path.insert(0, str(Path(__file__).parent))
from event_store import EventStore

BACKEND_PORT = int(os.environ.get("BACKEND_PORT", "8080"))
EVENT_LOG = os.environ.get("EVENT_LOG", "logs/events.jsonl")
TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
STATIC_DIR = Path(__file__).parent.parent / "static"

store = EventStore(log_path=EVENT_LOG)
_subscribers: list[asyncio.Queue] = []

_pty = None
_pty_alive = False
_pty_lock = threading.Lock()
_ws_clients: set = set()
_data_queue = queue.Queue(maxsize=5000)
_loop = None


def get_vpn_ip() -> str:
    env_ip = os.environ.get("VPN_IP", "")
    if env_ip:
        return env_ip
    for ts in ["tailscale", r"C:\Program Files\Tailscale\tailscale.exe"]:
        try:
            r = subprocess.run([ts, "ip", "-4"], capture_output=True, text=True, timeout=5)
            ip = r.stdout.strip()
            if ip and ip.startswith("100."):
                return ip
        except Exception:
            pass
    return ""


def broadcast_event(event: dict):
    for q in _subscribers:
        try:
            q.put_nowait(event)
        except Exception:
            pass


def _pty_reader_thread(pty_obj):
    global _pty_alive
    while _pty_alive:
        try:
            data = pty_obj.read()
            if data:
                try:
                    _data_queue.put_nowait(data)
                except queue.Full:
                    try:
                        _data_queue.get_nowait()
                    except Exception:
                        pass
                    _data_queue.put_nowait(data)
        except Exception as e:
            err = str(e).lower()
            if "dead" in err or "exit" in err or not _pty_alive:
                break
            time.sleep(0.05)
    _pty_alive = False
    _data_queue.put("__EXIT__")


def _do_start_pty():
    """Blocking PTY startup, runs in thread."""
    global _pty, _pty_alive

    if _pty_alive:
        return True

    try:
        import winpty
        pty = winpty.PTY(120, 36)
        home = os.path.expanduser("~")

        # Try to find claude directly
        claude_path = r"C:\Users\Administrator\.local\bin\claude.exe"
        if not os.path.isfile(claude_path):
            # Fallback: use where command with short timeout
            try:
                r = subprocess.run(
                    ["where", "claude"],
                    capture_output=True, text=True, timeout=3
                )
                lines = [l.strip() for l in r.stdout.strip().split("\n") if l.strip()]
                if lines:
                    claude_path = lines[0]
            except Exception:
                claude_path = ""

        if claude_path and os.path.isfile(claude_path):
            print(f"[PTY] Spawning: {claude_path}")
            pty.spawn(claude_path, cwd=home)
        else:
            print("[PTY] Fallback: cmd -> claude")
            pty.spawn(os.environ.get("COMSPEC", "cmd.exe"), cwd=home)
            time.sleep(0.5)
            pty.write("claude\r")

        with _pty_lock:
            _pty = pty
            _pty_alive = True

        t = threading.Thread(target=_pty_reader_thread, args=(pty,), daemon=True)
        t.start()

        store.add_event({"event": "session_start", "message": "Claude Code PTY started"})
        broadcast_event({"event": "session_start", "message": "Claude Code PTY started"})
        print(f"[PTY] Started, PID={pty.pid}")
        return True

    except Exception as e:
        print(f"[PTY] Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def stop_pty():
    global _pty, _pty_alive
    with _pty_lock:
        _pty_alive = False
        _pty = None
    _data_queue.put("__EXIT__")


def write_pty(data: str) -> bool:
    with _pty_lock:
        if _pty and _pty_alive:
            try:
                _pty.write(data)
                return True
            except Exception:
                return False
    return False


def resize_pty(cols: int, rows: int):
    with _pty_lock:
        if _pty and _pty_alive:
            try:
                _pty.set_size(cols, rows)
            except Exception:
                pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _loop
    _loop = asyncio.get_event_loop()
    task = asyncio.create_task(_relay_loop())
    yield
    task.cancel()
    stop_pty()


app = FastAPI(lifespan=lifespan)


async def _relay_loop():
    while True:
        try:
            data = await _loop.run_in_executor(
                None, lambda: _data_queue.get(timeout=0.02)
            )
        except queue.Empty:
            await asyncio.sleep(0.02)
            continue

        if data == "__EXIT__":
            msg = json.dumps({"type": "exit", "data": "Process exited"}, ensure_ascii=False)
            for ws in list(_ws_clients):
                try:
                    await ws.send_text(msg)
                except Exception:
                    pass
            continue

        chunks = [data]
        for _ in range(30):
            try:
                extra = _data_queue.get_nowait()
                if extra == "__EXIT__":
                    chunks.append(extra)
                    break
                chunks.append(extra)
            except queue.Empty:
                break

        combined = "".join(chunks)
        msg = json.dumps({"type": "data", "data": combined}, ensure_ascii=False)
        dead = set()
        for ws in list(_ws_clients):
            try:
                await ws.send_text(msg)
            except Exception:
                dead.add(ws)
        _ws_clients.difference_update(dead)


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    html = (TEMPLATES_DIR / "dashboard.html").read_text(encoding="utf-8")
    return HTMLResponse(html)


@app.get("/static/{filename:path}")
async def static_file(filename: str):
    fp = STATIC_DIR / filename
    if fp.exists():
        return FileResponse(fp)
    return HTMLResponse("Not found", status_code=404)


@app.get("/api/status")
async def status_api():
    s = store.get_status()
    s["terminal_running"] = _pty_alive
    return s


@app.post("/api/terminal/start")
async def terminal_start():
    if _pty_alive:
        return {"status": "already_running"}
    ok = await _loop.run_in_executor(None, _do_start_pty)
    return {"status": "started" if ok else "error"}


@app.post("/api/terminal/stop")
async def terminal_stop():
    stop_pty()
    return {"status": "stopped"}


@app.get("/api/events")
async def event_stream(request: Request):
    async def generate():
        q = asyncio.Queue()
        _subscribers.append(q)
        try:
            for e in store.get_events(since=0)[-20:]:
                yield f"data: {json.dumps(e, ensure_ascii=False)}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(q.get(), timeout=30)
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            _subscribers.remove(q)
    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})


@app.post("/api/hook")
async def receive_hook(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    event = {
        "event": body.get("hook_event_name", body.get("event", "unknown")),
        "tool": body.get("tool_name", body.get("tool", "")),
        "session_id": body.get("session_id", ""),
        "cwd": body.get("cwd", ""),
    }
    store.add_event(event)
    broadcast_event(event)
    return {"status": "ok"}


@app.get("/api/stats")
async def stats_api():
    return store.get_status()


@app.get("/api/history")
async def history_api(since: float = 0, limit: int = 50):
    return {"events": store.get_events(since=since)[-limit:]}


@app.websocket("/ws/terminal")
async def terminal_ws(websocket: WebSocket):
    await websocket.accept()
    _ws_clients.add(websocket)
    try:
        await websocket.send_text(json.dumps({
            "type": "status",
            "terminal_running": _pty_alive
        }))
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
                if msg.get("type") == "input":
                    write_pty(msg.get("data", ""))
                elif msg.get("type") == "resize":
                    resize_pty(msg.get("cols", 120), msg.get("rows", 36))
            except (json.JSONDecodeError, KeyError):
                pass
    except WebSocketDisconnect:
        pass
    finally:
        _ws_clients.discard(websocket)


if __name__ == "__main__":
    ip = get_vpn_ip()
    if not ip:
        print("ERROR: VPN IP not detected")
        sys.exit(1)
    print(f"VPN IP: {ip}")
    print(f"Dashboard: http://{ip}:{BACKEND_PORT}")
    uvicorn.run(app, host="0.0.0.0", port=BACKEND_PORT)
