# -*- coding: utf-8 -*-
"""Agent Hub Backend - Main entry point."""

import os, subprocess, asyncio, json, sys, time, threading, queue
from pathlib import Path
from contextlib import asynccontextmanager

import yaml
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse

import uvicorn

sys.path.insert(0, str(Path(__file__).parent))
from event_store import EventStore
from session_manager import SessionManager

# === Config ===
BACKEND_PORT = int(os.environ.get("BACKEND_PORT", "8080"))
EVENT_LOG = os.environ.get("EVENT_LOG", "logs/events.jsonl")
TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
STATIC_DIR = Path(__file__).parent.parent / "static"
AGENTS_YAML = Path(__file__).parent.parent / "agents.yaml"

store = EventStore(log_path=EVENT_LOG)
session_mgr = SessionManager()
_subscribers: list[asyncio.Queue] = []
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


def load_agents_config() -> dict:
    """Load agents.yaml and auto-detect installed agents."""
    with open(AGENTS_YAML, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    agents = config.get("agents", {})
    for agent_id, agent in agents.items():
        cmd = agent.get("command", "")
        detected = False
        try:
            r = subprocess.run(["where", cmd], capture_output=True, text=True, timeout=3)
            detected = bool(r.stdout.strip())
        except Exception:
            pass
        agent["detected"] = detected

    return agents


def broadcast_event(event: dict):
    for q in _subscribers:
        try:
            q.put_nowait(event)
        except Exception:
            pass


def parse_voice_command(text: str) -> dict:
    """Parse voice text into command or input."""
    t = text.strip().lower()
    agents_config = load_agents_config()
    agent_ids = list(agents_config.keys())
    agent_names = {aid: agents_config[aid].get("name", "").lower() for aid in agent_ids}
    # Also map by command name
    agent_cmds = {agents_config[aid].get("command", "").lower(): aid for aid in agent_ids}

    # Find mentioned agent
    target_agent = None
    for aid in agent_ids:
        name = agent_names.get(aid, "")
        cmd = agents_config[aid].get("command", "").lower()
        if name and name in t:
            target_agent = aid
            break
        if cmd and cmd in t:
            target_agent = aid
            break

    # Control commands
    if any(kw in t for kw in ["start", "qi dong", "\u542f\u52a8", "\u5f00\u59cb"]):
        if target_agent:
            return {"type": "command", "action": "start", "agent_id": target_agent}

    if any(kw in t for kw in ["stop", "ting zhi", "\u505c\u6b62", "\u5173\u95ed"]):
        if target_agent:
            return {"type": "command", "action": "stop", "agent_id": target_agent}
        if any(kw in t for kw in ["all", "\u6240\u6709", "\u5168\u90e8"]):
            return {"type": "command", "action": "stop_all"}

    if any(kw in t for kw in ["switch", "\u5207\u6362"]):
        if target_agent:
            return {"type": "command", "action": "switch", "agent_id": target_agent}

    if any(kw in t for kw in ["split", "\u5206\u5c4f"]):
        if "2" in t or "\u4e8c" in t:
            return {"type": "command", "action": "split", "layout": "2"}
        if "4" in t or "\u56db" in t:
            return {"type": "command", "action": "split", "layout": "4"}
        return {"type": "command", "action": "split", "layout": "2"}

    if any(kw in t for kw in ["fullscreen", "\u5168\u5c4f"]):
        return {"type": "command", "action": "fullscreen"}

    # Default: input to current focus
    return {"type": "input", "data": text}


# === FastAPI ===

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _loop
    _loop = asyncio.get_event_loop()
    session_mgr.set_loop(_loop)
    task = asyncio.create_task(_relay_all_loops())
    yield
    task.cancel()

app = FastAPI(lifespan=lifespan)


async def _relay_all_loops():
    """Poll all session queues and relay data to WS clients."""
    while True:
        try:
            sessions = session_mgr.list_sessions()
            for s_info in sessions:
                sid = s_info["session_id"]
                session = session_mgr.get_session(sid)
                if not session:
                    continue

                # Drain queue
                chunks = []
                for _ in range(30):
                    try:
                        data = session.data_queue.get_nowait()
                        if data == "__EXIT__":
                            chunks.append(data)
                            break
                        chunks.append(data)
                    except queue.Empty:
                        break

                if not chunks:
                    continue

                combined = "".join(chunks)
                is_exit = "__EXIT__" in combined
                if is_exit:
                    combined = combined.replace("__EXIT__", "")

                if combined:
                    msg = json.dumps({"type": "data", "data": combined, "session_id": sid}, ensure_ascii=False)
                    dead = set()
                    for ws in list(session.ws_clients):
                        try:
                            await ws.send_text(msg)
                        except Exception:
                            dead.add(ws)
                    session.ws_clients.difference_update(dead)

                if is_exit:
                    msg = json.dumps({"type": "exit", "session_id": sid}, ensure_ascii=False)
                    for ws in list(session.ws_clients):
                        try:
                            await ws.send_text(msg)
                        except Exception:
                            pass

            await asyncio.sleep(0.02)
        except asyncio.CancelledError:
            break
        except Exception:
            await asyncio.sleep(0.1)


# --- Pages ---
@app.get("/", response_class=HTMLResponse)
async def dashboard():
    html = (TEMPLATES_DIR / "dashboard.html").read_text(encoding="utf-8")
    return HTMLResponse(html)

# --- Static ---
@app.get("/static/{filename:path}")
async def static_file(filename: str):
    fp = STATIC_DIR / filename
    if fp.exists():
        return FileResponse(fp)
    return HTMLResponse("Not found", status_code=404)

# --- Agent API ---
@app.get("/api/agents")
async def list_agents():
    agents = load_agents_config()
    result = []
    for aid, cfg in agents.items():
        if cfg.get("detected"):
            result.append({
                "id": aid,
                "name": cfg.get("name", aid),
                "command": cfg.get("command", ""),
                "icon": cfg.get("icon", "\u25a1"),
                "color": cfg.get("color", "#58a6ff"),
                "bg_color": cfg.get("bg_color", "#161b22"),
                "description": cfg.get("description", ""),
            })
    return result

# --- Session API ---
@app.get("/api/sessions")
async def list_sessions():
    return session_mgr.list_sessions()

@app.post("/api/sessions")
async def create_session(request: Request):
    body = await request.json()
    agent_id = body.get("agent_id", "")
    working_dir = body.get("working_dir")

    agents = load_agents_config()
    if agent_id not in agents:
        return {"status": "error", "message": f"Agent {agent_id} not found"}

    session = session_mgr.create_session(agent_id, agents[agent_id], working_dir)
    if session is None:
        return {"status": "error", "message": "Failed to start session"}

    store.add_event({"event": "session_start", "agent_id": agent_id, "session_id": session.session_id})
    broadcast_event({"event": "session_start", "agent_id": agent_id, "session_id": session.session_id})
    return {"status": "started", "session": session.to_dict()}

@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    ok = session_mgr.stop_session(session_id)
    if ok:
        store.add_event({"event": "session_stop", "session_id": session_id})
        broadcast_event({"event": "session_stop", "session_id": session_id})
    return {"status": "stopped" if ok else "not_found"}

# --- Voice ---
@app.post("/api/voice/command")
async def voice_command(request: Request):
    body = await request.json()
    text = body.get("text", "")
    if not text:
        return {"status": "empty"}

    parsed = parse_voice_command(text)

    if parsed["type"] == "command":
        action = parsed["action"]

        if action == "start":
            agent_id = parsed["agent_id"]
            agents = load_agents_config()
            if agent_id not in agents:
                return {"status": "error", "message": f"Agent not found: {agent_id}"}
            session = session_mgr.create_session(agent_id, agents[agent_id])
            if session:
                store.add_event({"event": "voice_start", "agent_id": agent_id, "session_id": session.session_id})
                broadcast_event({"event": "voice_start", "agent_id": agent_id, "session_id": session.session_id})
                return {"status": "started", "session": session.to_dict(), "parsed": parsed}
            return {"status": "error", "message": "Failed to start"}

        elif action == "stop":
            agent_id = parsed.get("agent_id")
            if agent_id:
                sessions = session_mgr.list_sessions()
                for s in sessions:
                    if s["agent_id"] == agent_id and s["status"] == "running":
                        session_mgr.stop_session(s["session_id"])
                return {"status": "stopped", "parsed": parsed}
            return {"status": "no_target"}

        elif action == "stop_all":
            sessions = session_mgr.list_sessions()
            for s in sessions:
                if s["status"] == "running":
                    session_mgr.stop_session(s["session_id"])
            return {"status": "all_stopped", "parsed": parsed}

        return {"status": "command", "parsed": parsed}

    # Plain input - return for frontend to handle
    return {"status": "input", "text": text, "parsed": parsed}

# --- Events ---
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

# --- WebSocket Terminal ---
@app.websocket("/ws/terminal/{session_id}")
async def terminal_ws(websocket: WebSocket, session_id: str):
    await websocket.accept()
    session = session_mgr.get_session(session_id)
    if not session:
        await websocket.send_text(json.dumps({"type": "error", "message": "Session not found"}))
        await websocket.close()
        return

    session.ws_clients.add(websocket)
    try:
        await websocket.send_text(json.dumps({"type": "status", "session_id": session_id, "alive": session.alive}))
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
                if msg.get("type") == "input":
                    session_mgr.write_to_session(session_id, msg.get("data", ""))
                elif msg.get("type") == "resize":
                    session_mgr.resize_session(session_id, msg.get("cols", 120), msg.get("rows", 36))
            except (json.JSONDecodeError, KeyError):
                pass
    except WebSocketDisconnect:
        pass
    finally:
        session.ws_clients.discard(websocket)

# === Main ===
if __name__ == "__main__":
    ip = get_vpn_ip()
    if not ip:
        print("ERROR: VPN IP not detected")
        sys.exit(1)
    print(f"VPN IP: {ip}")
    print(f"Agent Hub: http://{ip}:{BACKEND_PORT}")
    uvicorn.run(app, host="0.0.0.0", port=BACKEND_PORT)
