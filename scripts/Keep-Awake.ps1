# Keep-Awake.ps1 - 防止 Windows 休眠
# 使用 Windows API SetThreadExecutionState

# 加载 Windows API
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class PowerUtil {
    [DllImport("kernel32.dll", CharSet=CharSet.Auto, SetLastError=true)]
    public static extern uint SetThreadExecutionState(uint esFlags);

    public const uint ES_CONTINUOUS = 0x80000000;
    public const uint ES_SYSTEM_REQUIRED = 0x00000001;
    public const uint ES_DISPLAY_REQUIRED = 0x00000002;
}
"@

Write-Host "Keep-Awake: 防止系统休眠 (Ctrl+C 停止)" -ForegroundColor Cyan

# 设置持续唤醒状态（系统 + 显示器）
[PowerUtil]::SetThreadExecutionState(
    [PowerUtil]::ES_CONTINUOUS -bor
    [PowerUtil]::ES_SYSTEM_REQUIRED -bor
    [PowerUtil]::ES_DISPLAY_REQUIRED
) | Out-Null

# 写入 PID 文件
$pidFile = Join-Path $PSScriptRoot "..\logs\keep-awake.pid"
$PID | Out-File $pidFile -Encoding utf8

try {
    # 持续运行，每60秒刷新一次
    while ($true) {
        Start-Sleep -Seconds 60
        [PowerUtil]::SetThreadExecutionState(
            [PowerUtil]::ES_SYSTEM_REQUIRED
        ) | Out-Null
    }
} finally {
    # 恢复正常电源管理
    [PowerUtil]::SetThreadExecutionState([PowerUtil]::ES_CONTINUOUS) | Out-Null
    Write-Host "Keep-Awake: 已恢复正常电源管理" -ForegroundColor Yellow
    Remove-Item $pidFile -ErrorAction SilentlyContinue
}
