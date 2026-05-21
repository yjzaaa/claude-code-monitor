# -*- coding: utf-8 -*-
"""Session Manager - Manages multiple PTY sessions for different agents."""

import os
import subprocess
import threading
import queue
import time
from dataclasses import dataclass, field


@dataclass
class AgentSession:
    session_id: str
    agent_id: str
    agent_name: str
    command: str
    icon: str
    color: str
    working_dir: str
    pty: object = None
    alive: bool = False
    ws_clients: set = field(default_factory=set)
    data_queue: queue.Queue = field(default_factory=lambda: queue.Queue(maxsize=5000))
    started_at: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _loop: object = None

    @property
    def status(self):
        with self._lock:
            return "running" if self.alive else "stopped"

    @property
    def uptime(self):
        if self.started_at and self.alive:
            return round(time.time() - self.started_at, 1)
        return 0.0

    def to_dict(self):
        return {
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "command": self.command,
            "icon": self.icon,
            "color": self.color,
            "working_dir": self.working_dir,
            "status": self.status,
            "uptime": self.uptime,
            "started_at": self.started_at,
        }


class SessionManager:
    def __init__(self):
        self._sessions: dict[str, AgentSession] = {}
        self._lock = threading.Lock()
        self._loop = None
        self._counter = 0

    def set_loop(self, loop):
        self._loop = loop

    def _next_id(self, agent_id: str) -> str:
        self._counter += 1
        return f"{agent_id}-{self._counter}"

    def create_session(self, agent_id: str, agent_config: dict, working_dir: str = None) -> AgentSession:
        """Create and start a new agent session."""
        if working_dir is None:
            working_dir = os.path.expanduser("~")

        session_id = self._next_id(agent_id)
        session = AgentSession(
            session_id=session_id,
            agent_id=agent_id,
            agent_name=agent_config.get("name", agent_id),
            command=agent_config["command"],
            icon=agent_config.get("icon", "\u25a1"),
            color=agent_config.get("color", "#58a6ff"),
            working_dir=working_dir,
            _loop=self._loop,
        )

        # Start PTY
        ok = self._start_pty(session, agent_config)
        if not ok:
            return None

        with self._lock:
            self._sessions[session_id] = session

        return session

    def _start_pty(self, session: AgentSession, agent_config: dict) -> bool:
        """Spawn PTY process for a session."""
        try:
            import winpty
            pty = winpty.PTY(120, 36)

            cmd = agent_config["command"]
            use_shell = agent_config.get("shell", False)

            if use_shell:
                pty.spawn(os.environ.get("COMSPEC", "cmd.exe"), cwd=session.working_dir)
                time.sleep(0.3)
                pty.write(cmd + "\r")
            else:
                # Find command path
                cmd_path = cmd
                try:
                    r = subprocess.run(["where", cmd], capture_output=True, text=True, timeout=3)
                    lines = [l.strip() for l in r.stdout.strip().split("\n") if l.strip()]
                    if lines:
                        cmd_path = lines[0]
                except Exception:
                    pass

                if os.path.isfile(cmd_path):
                    pty.spawn(cmd_path, cwd=session.working_dir)
                else:
                    # Fallback to cmd
                    pty.spawn(os.environ.get("COMSPEC", "cmd.exe"), cwd=session.working_dir)
                    time.sleep(0.3)
                    pty.write(cmd + "\r")

            with session._lock:
                session.pty = pty
                session.alive = True
                session.started_at = time.time()

            # Start reader thread
            t = threading.Thread(target=self._reader_thread, args=(session,), daemon=True)
            t.start()

            print(f"[SessionManager] Started {session.session_id} (PID={pty.pid})")
            return True

        except Exception as e:
            print(f"[SessionManager] Failed to start {session.session_id}: {e}")
            return False

    def _reader_thread(self, session: AgentSession):
        """Read from PTY in background, push to queue."""
        while True:
            with session._lock:
                if not session.alive or session.pty is None:
                    break
                pty = session.pty

            try:
                data = pty.read()
                if data:
                    try:
                        session.data_queue.put_nowait(data)
                    except queue.Full:
                        try:
                            session.data_queue.get_nowait()
                        except Exception:
                            pass
                        session.data_queue.put_nowait(data)
            except Exception as e:
                err = str(e).lower()
                if "dead" in err or "exit" in err:
                    break
                time.sleep(0.05)

        with session._lock:
            session.alive = False
        session.data_queue.put("__EXIT__")
        print(f"[SessionManager] Session {session.session_id} exited")

    def stop_session(self, session_id: str) -> bool:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return False

        with session._lock:
            session.alive = False
            session.pty = None
        session.data_queue.put("__EXIT__")
        return True

    def get_session(self, session_id: str) -> AgentSession | None:
        with self._lock:
            return self._sessions.get(session_id)

    def list_sessions(self) -> list[dict]:
        with self._lock:
            return [s.to_dict() for s in self._sessions.values()]

    def write_to_session(self, session_id: str, data: str) -> bool:
        with self._lock:
            session = self._sessions.get(session_id)
        if not session:
            return False
        with session._lock:
            if session.pty and session.alive:
                try:
                    session.pty.write(data)
                    return True
                except Exception:
                    return False
        return False

    def resize_session(self, session_id: str, cols: int, rows: int) -> bool:
        with self._lock:
            session = self._sessions.get(session_id)
        if not session:
            return False
        with session._lock:
            if session.pty and session.alive:
                try:
                    session.pty.set_size(cols, rows)
                    return True
                except Exception:
                    pass
        return False
