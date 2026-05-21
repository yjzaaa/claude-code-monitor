# Claude Code Monitor

Windows 版 Claude Code 移动端监控工具 - 通过手机浏览器实时监控电脑上 Claude Code 智能体的运行状态。

参考项目: [buckle42/claude-code-remote](https://github.com/buckle42/claude-code-remote) (macOS 版)

## 功能

- **实时监控仪表盘** - 运行状态、时长、工具统计一目了然
- **事件流** - 实时滚动显示 Claude Code 的工具调用、状态变化
- **终端交互** - 通过 ttyd 在手机上操作 Claude Code 终端
- **快捷键** - 常用快捷键按钮，适配手机触屏
- **语音输入** - 支持手机原生语音听写输入指令
- **零公网暴露** - 所有服务仅绑定 VPN IP

## 架构

```
手机 (浏览器)
  ↓ Tailscale/ZeroTier VPN (WireGuard 加密)
  ↓
Windows 电脑
  ├── FastAPI 后端 (:8080)
  │   ├── 监控仪表盘 (移动端优化)
  │   ├── SSE 实时事件流
  │   └── Hook 事件接收器
  ├── ttyd (:7681) → Web 终端
  └── Claude Code CLI → Hooks → 事件推送
```

## 快速开始

### 1. 安装依赖

```powershell
.\scripts\Install-Prerequisites.ps1
```

### 2. 配置 VPN

- 电脑端安装 [Tailscale](https://tailscale.com/download/windows) 或 [ZeroTier](https://www.zerotier.com/download/)
- 手机端安装同一 VPN 应用，用相同账号登录
- 确认两设备可以互相访问

### 3. 配置 Claude Code Hooks

将 `config/claude-hooks.json` 的内容复制到 `~/.claude/settings.json` 的 `hooks` 字段中。

或运行以下命令自动配置：

```powershell
# 读取现有配置，合并 hooks
$settingsPath = "$env:USERPROFILE\.claude\settings.json"
$hooks = Get-Content ".\config\claude-hooks.json" | ConvertFrom-Json
# ... 手动合并到 settings.json
```

### 4. 启动服务

```powershell
.\scripts\Start-Monitor.ps1
```

输出示例：
```
=== 服务已启动 ===

  监控仪表盘:  http://100.x.y.z:8080
  终端 (ttyd): http://100.x.y.z:7681

在手机上打开监控仪表盘地址 (需要连接同一 VPN)
```

### 5. 手机访问

1. 打开手机上的 VPN 应用，确认已连接
2. 浏览器打开 `http://100.x.y.z:8080`
3. 建议添加到主屏幕，之后像 App 一样使用

### 6. 停止服务

```powershell
.\scripts\Stop-Monitor.ps1
```

## 费用

完全免费。所有工具均为开源或有免费额度：

| 工具 | 费用 |
|------|------|
| Tailscale | 个人免费 (最多 3 用户, 100 设备) |
| ZeroTier | 个人免费 (最多 25 设备) |
| ttyd | 开源免费 |
| FastAPI + Uvicorn | 开源免费 |

唯一成本是你现有的 Claude Code API 使用量。

## 安全说明

- 所有服务**仅绑定 VPN 接口 IP**，不暴露到公网
- Tailscale/ZeroTier 创建 WireGuard 加密隧道
- 每个设备必须通过 SSO 认证
- 无端口转发、无公网暴露

**注意**: 此配置提供完整的终端访问权限。拥有你 Tailscale 账户权限的人可以操作你的终端。

## 目录结构

```
claude-code-monitor/
├── scripts/           # PowerShell 启停脚本
├── backend/           # FastAPI 后端
├── templates/         # HTML 模板
├── config/            # 配置模板
└── logs/              # 运行日志
```

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `VPN_TYPE` | `tailscale` | VPN 类型: tailscale / zerotier |
| `TTYD_PORT` | `7681` | ttyd 端口 |
| `BACKEND_PORT` | `8080` | 后端端口 |
| `EVENT_LOG` | `logs/events.jsonl` | 事件日志文件 |
