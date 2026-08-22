param(
    [string]$TaskName = "我的生活中枢-每日提醒"
)

$ErrorActionPreference = "Stop"

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $task) {
    Write-Output "本来就没有设置每日提醒，无需移除。"
    Read-Host "按回车关闭"
    exit 0
}

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Output "已移除每日提醒。程序本身不受影响。"
Read-Host "按回车关闭"
