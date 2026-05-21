# Install-Prerequisites.ps1 - 安装依赖
# 用法: .\scripts\Install-Prerequisites.ps1

$ErrorActionPreference = "Stop"

Write-Host "=== Claude Code Monitor - 依赖检查 ===" -ForegroundColor Cyan

# 检查 Python
Write-Host "`n[1/4] 检查 Python..." -ForegroundColor Yellow
try {
    $pyVer = python --version 2>&1
    Write-Host "  OK: $pyVer" -ForegroundColor Green
} catch {
    Write-Host "  ERROR: 未找到 Python，请安装 Python 3.9+" -ForegroundColor Red
    Write-Host "  下载: https://www.python.org/downloads/" -ForegroundColor Gray
    exit 1
}

# 检查 pip 依赖
Write-Host "`n[2/4] 检查 Python 依赖..." -ForegroundColor Yellow
$backendDir = Join-Path $PSScriptRoot "..\backend"
pip install -r "$backendDir\requirements.txt"
if ($LASTEXITCODE -eq 0) {
    Write-Host "  OK: FastAPI + Uvicorn 已安装" -ForegroundColor Green
} else {
    Write-Host "  ERROR: 安装 Python 依赖失败" -ForegroundColor Red
    exit 1
}

# 检查 ttyd
Write-Host "`n[3/4] 检查 ttyd..." -ForegroundColor Yellow
$ttydCmd = Get-Command ttyd -ErrorAction SilentlyContinue
if ($ttydCmd) {
    Write-Host "  OK: ttyd 已安装" -ForegroundColor Green
} else {
    Write-Host "  ttyd 未安装，尝试下载..." -ForegroundColor Yellow
    $ttydDir = Join-Path $PSScriptRoot "..\bin"
    New-Item -ItemType Directory -Force -Path $ttydDir | Out-Null

    # 检测架构
    $arch = if ([Environment]::Is64BitOperatingSystem) { "x86_64" } else { "i686" }
    $url = "https://github.com/tsl0922/ttyd/releases/latest/download/ttyd.win32.exe"

    Write-Host "  下载 ttyd 从 $url ..." -ForegroundColor Gray
    try {
        Invoke-WebRequest -Uri $url -OutFile "$ttydDir\ttyd.exe" -UseBasicParsing
        Write-Host "  OK: ttyd 已下载到 $ttydDir\ttyd.exe" -ForegroundColor Green
        Write-Host "  请将 $ttydDir 添加到系统 PATH" -ForegroundColor Yellow
    } catch {
        Write-Host "  WARN: 自动下载失败，请手动下载 ttyd" -ForegroundColor Yellow
        Write-Host "  地址: https://github.com/tsl0922/ttyd/releases" -ForegroundColor Gray
    }
}

# 检查 VPN
Write-Host "`n[4/4] 检查 VPN..." -ForegroundColor Yellow
$ts = Get-Command tailscale -ErrorAction SilentlyContinue
$zt = Get-Command zerotier-cli -ErrorAction SilentlyContinue
if ($ts) {
    $tsIp = (tailscale ip -4 2>$null).Trim()
    if ($tsIp) {
        Write-Host "  OK: Tailscale 已连接 (IP: $tsIp)" -ForegroundColor Green
    } else {
        Write-Host "  WARN: Tailscale 已安装但未连接" -ForegroundColor Yellow
    }
} elseif ($zt) {
    Write-Host "  OK: ZeroTier 已安装" -ForegroundColor Green
} else {
    Write-Host "  WARN: 未检测到 Tailscale 或 ZeroTier" -ForegroundColor Yellow
    Write-Host "  请安装其一:" -ForegroundColor Gray
    Write-Host "    Tailscale: https://tailscale.com/download/windows" -ForegroundColor Gray
    Write-Host "    ZeroTier:  https://www.zerotier.com/download/" -ForegroundColor Gray
}

Write-Host "`n=== 检查完成 ===" -ForegroundColor Cyan
Write-Host "运行 '.\scripts\Start-Monitor.ps1' 启动服务" -ForegroundColor White
