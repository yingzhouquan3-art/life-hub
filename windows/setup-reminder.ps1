param(
    [string]$Time = "",
    [string]$TaskName = "我的生活中枢-每日提醒"
)

# 注册一个每天定时跑的提醒。用的是当前用户的计划任务，不需要管理员权限，
# 也不改任何系统设置——只在你自己的任务列表里加一条，随时可以删。

$ErrorActionPreference = "Stop"
$scriptPath = Join-Path $PSScriptRoot "remind.ps1"

if (-not (Test-Path $scriptPath)) {
    Write-Output "找不到 remind.ps1，请确认项目文件完整。"
    Read-Host "按回车关闭"
    exit 1
}

if (-not $Time) {
    Write-Output "每天几点提醒你？（24 小时制，例如 21:30。直接回车用 21:00）"
    $Time = Read-Host "时间"
    if (-not $Time) { $Time = "21:00" }
}

try {
    $at = [datetime]::ParseExact($Time.Trim(), "HH:mm", $null)
} catch {
    Write-Output "看不懂这个时间：$Time。请写成 21:30 这样的格式。"
    Read-Host "按回车关闭"
    exit 1
}

$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$scriptPath`""
$trigger = New-ScheduledTaskTrigger -Daily -At $at
# 不在电池上被跳过；错过了就补一次——笔记本合盖是常态，不该因此漏提醒。
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -StartWhenAvailable -Hidden `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Description "生活中枢：只在今天什么都没记时提醒" -Force | Out-Null

Write-Output ""
Write-Output "已设置每天 $($at.ToString('HH:mm')) 提醒。"
Write-Output "它只在你当天什么都没记的时候才出声；记过了就不打扰。"
Write-Output "服务没在运行时也不会弹——那多半说明你不在电脑前。"
Write-Output ""
Write-Output "想取消：双击「移除每日提醒.cmd」。"
Write-Output ""

# 立刻发一条测试通知。通知这种东西「设置成功」不等于「你看得到」——
# Windows 会因为专注助手、通知权限等原因静默丢掉，而脚本这边完全无感。
# 当场发一条，你现在就能确认，而不是等到某天晚上才发现它一直没响过。
Write-Output "正在发一条测试通知，请留意屏幕右下角……"
& (Join-Path $PSScriptRoot "remind.ps1") -Test | Out-Null
Write-Output ""
Write-Output "看到那条通知了吗？"
Write-Output "  看到了 —— 设置完成，不用再做什么。"
Write-Output "  没看到 —— 打开「设置 → 系统 → 通知」，确认通知总开关是打开的，"
Write-Output "            并且「专注助手 / 请勿打扰」没有开着。"
Read-Host "按回车关闭"
