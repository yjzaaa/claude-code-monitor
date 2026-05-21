# Stop-Monitor.ps1 - 停止所有服务
# 用法: .\scripts\Stop-Monitor.ps1

$ProjectDir = Resolve-Path (Join-Path $PSScriptRoot "..")
$LogDir = Join-Path $ProjectDir "logs"

Write-Host "=== 停止 Claude Code Monitor ===" -ForegroundColor Cyan

# 停止 ttyd
$ttydPidFile = Join-Path $LogDir "ttyd.pid"
if (Test-Path $ttydPidFile) {
    $pid = Get-Content $ttydPidFile -ErrorAction SilentlyContinue
    if ($pid) {
        Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
        Write-Host "  ttyd 已停止" -ForegroundColor Green
    }
    Remove-Item $ttydPidFile -ErrorAction SilentlyContinue
} else {
    Get-Process -Name "ttyd" -ErrorAction SilentlyContinue | Stop-Process -Force
    Write-Host "  ttyd 已停止" -ForegroundColor Green
}

# 停止后端
$backendPidFile = Join-Path $LogDir "backend.pid"
if (Test-Path $backendPidFile) {
    $pid = Get-Content $backendPidFile -ErrorAction SilentlyContinue
    if ($pid) {
        Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
        Write-Host "  后端已停止" -ForegroundColor Green
    }
    Remove-Item $backendPidFile -ErrorAction SilentlyContinue
}

# 停止防休眠
$awakePidFile = Join-Path $LogDir "keep-awake.pid"
if (Test-Path $awakePidFile) {
    $pid = Get-Content $awakePidFile -ErrorAction SilentlyContinue
    if ($pid) {
        Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
        Write-Host "  防休眠已停止" -ForegroundColor Green
    }
    Remove-Item $awakePidFile -ErrorAction SilentlyContinue
}

Write-Host "`n所有服务已停止。" -ForegroundColor Cyan
