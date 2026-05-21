# Claude Code Monitor

## What This Is
Windows 版 Claude Code 移动端监控工具。通过 Tailscale/ZeroTier VPN 从手机浏览器实时监控电脑上 Claude Code 的运行状态、工具调用、事件日志，并支持远程交互。

## Architecture
```
Phone (Browser)
  ↓ Tailscale/ZeroTier VPN (WireGuard encrypted)
  ↓
Windows PC
  ├── FastAPI Backend (:8080)
  │   ├── Dashboard UI (monitoring + interaction)
  │   ├── SSE event stream (/api/events)
  │   └── Hook receiver (/api/hook)
  ├── ttyd (:7681) → Terminal web access
  └── Claude Code CLI → Hooks → POST events to backend
```

## File Overview
| File | Purpose |
|------|---------|
| `scripts/Start-Monitor.ps1` | Starts ttyd, backend, keep-awake |
| `scripts/Stop-Monitor.ps1` | Stops all services |
| `scripts/Install-Prerequisites.ps1` | Checks/installs dependencies |
| `scripts/Keep-Awake.ps1` | Prevents Windows from sleeping |
| `backend/main.py` | FastAPI app (dashboard + API + SSE) |
| `backend/event_store.py` | In-memory + JSONL event storage |
| `templates/dashboard.html` | Mobile-optimized monitoring dashboard |
| `templates/terminal.html` | Terminal page wrapping ttyd |
| `config/claude-hooks.json` | Claude Code hooks config template |

## Prerequisites
- Windows 10/11
- Python 3.9+
- ttyd (auto-downloaded by install script)
- Tailscale or ZeroTier (installed on PC and phone)
- Claude Code CLI

## Setup
1. Run `.\scripts\Install-Prerequisites.ps1`
2. Install Tailscale/ZeroTier on phone, sign in with same account
3. Run `.\scripts\Start-Monitor.ps1`
4. Open the dashboard URL on phone browser

## Security
All services bind exclusively to VPN IP. No ports exposed to public internet.
