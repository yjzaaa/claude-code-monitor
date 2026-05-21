# Start-Monitor.ps1 - 启动所有服务
# 用法: .\scripts\Start-Monitor.ps1

$ErrorActionPreference = "Stop"
$ProjectDir = Resolve-Path (Join-Path $PSScriptRoot "..")
$LogDir = Join-Path $ProjectDir "logs"
$BackendDir = Join-Path $ProjectDir "backend"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

Write-Host "=== Claude Code Monitor 启动 ===" -ForegroundColor Cyan

# 1. 检测 VPN IP
Write-Host "`n[1/4] 检测 VPN..." -ForegroundColor Yellow
$VpnIP = ""

# 尝试 Tailscale
$ts = Get-Command tailscale -ErrorAction SilentlyContinue
if ($ts) {
    $tsIp = (tailscale ip -4 2>$null).Trim()
    if ($tsIp -and $tsIp.StartsWith("100.")) {
        $VpnIP = $tsIp
        Write-Host "  Tailscale IP: $VpnIP" -ForegroundColor Green
    }
}

# 回退 ZeroTier
if (-not $VpnIP) {
    $zt = Get-Command zerotier-cli -ErrorAction SilentlyContinue
    if ($zt) {
        $networks = zerotier-cli listnetworks 2>$null
        foreach ($line in $networks -split "`n") {
            $parts = $line -split '\s+'
            foreach ($p in $parts) {
                if ($p -match '^(10\.|172\.|100\.)') {
                    $VpnIP = $p -replace '/\d+$',''
                    break
                }
            }
            if ($VpnIP) { break }
        }
        if ($VpnIP) {
            Write-Host "  ZeroTier IP: $VpnIP" -ForegroundColor Green
        }
    }
}

if (-not $VpnIP) {
    Write-Host "  ERROR: 未检测到 VPN IP" -ForegroundColor Red
    Write-Host "  请先启动 Tailscale 或 ZeroTier" -ForegroundColor Yellow
    exit 1
}

# 2. 启动 ttyd
Write-Host "`n[2/4] 启动 ttyd 终端..." -ForegroundColor Yellow
$ttydExe = Get-Command ttyd -ErrorAction SilentlyContinue
if (-not $ttydExe) {
    # 检查本地 bin 目录
    $localTtyd = Join-Path $ProjectDir "bin\ttyd.exe"
    if (Test-Path $localTtyd) {
        $ttydExe = $localTtyd
    } else {
        Write-Host "  ERROR: 未找到 ttyd" -ForegroundColor Red
        Write-Host "  运行 Install-Prerequisites.ps1 安装" -ForegroundColor Yellow
        exit 1
    }
}

# 停止已有的 ttyd 进程
Get-Process -Name "ttyd" -ErrorAction SilentlyContinue | Stop-Process -Force

$ttydPort = $env:TTYD_PORT ?? "7681"
$ttydProc = Start-Process -FilePath $ttydExe.Source -ArgumentList @(
    "--port", $ttydPort,
    "--interface", $VpnIP,
    "--writable",
    "claude"
) -PassThru -WindowStyle Hidden

$ttydProc.Id | Out-File (Join-Path $LogDir "ttyd.pid") -Encoding utf8
Write-Host "  ttyd 运行中 (PID: $($ttydProc.Id)) - http://${VpnIP}:${ttydPort}" -ForegroundColor Green

# 3. 启动 FastAPI 后端
Write-Host "`n[3/4] 启动监控后端..." -ForegroundColor Yellow
Get-Process -Name "python" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match "main.py" } |
    Stop-Process -Force -ErrorAction SilentlyContinue

$backendPort = $env:BACKEND_PORT ?? "8080"
$env:BACKEND_PORT = $backendPort
$env:TTYD_PORT = $ttydPort

$backendProc = Start-Process -FilePath "python" -ArgumentList @(
    (Join-Path $BackendDir "main.py")
) -PassThru -WindowStyle Hidden

$backendProc.Id | Out-File (Join-Path $LogDir "backend.pid") -Encoding utf8
Write-Host "  后端运行中 (PID: $($backendProc.Id)) - http://${VpnIP}:${backendPort}" -ForegroundColor Green

# 4. 启动防休眠
Write-Host "`n[4/4] 启动防休眠..." -ForegroundColor Yellow
$awakeProc = Start-Process -FilePath "powershell" -ArgumentList @(
    "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
    (Join-Path $PSScriptRoot "Keep-Awake.ps1")
) -PassThru -WindowStyle Hidden

$awakeProc.Id | Out-File (Join-Path $LogDir "keep-awake.pid") -Encoding utf8
Write-Host "  防休眠运行中 (PID: $($awakeProc.Id))" -ForegroundColor Green

# 完成
Start-Sleep -Seconds 2
Write-Host ""
Write-Host "=== 服务已启动 ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "  监控仪表盘:  http://${VpnIP}:${backendPort}" -ForegroundColor White
Write-Host "  终端 (ttyd): http://${VpnIP}:${ttydPort}" -ForegroundColor White
Write-Host ""
Write-Host "在手机上打开监控仪表盘地址 (需要连接同一 VPN)" -ForegroundColor Yellow
Write-Host "停止服务: .\scripts\Stop-Monitor.ps1" -ForegroundColor Gray
