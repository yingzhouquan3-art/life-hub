param(
    [switch]$Silent
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$dataDir = Join-Path $projectRoot "data"
$pidFile = Join-Path $dataDir "server-process.json"
$appPort = 8766
$messagesPath = Join-Path $PSScriptRoot "messages.json"
$messages = Get-Content -Raw -Encoding UTF8 $messagesPath | ConvertFrom-Json

Add-Type -AssemblyName PresentationFramework

function Show-Info([string]$text) {
    if ($Silent) {
        Write-Output $text
        return
    }
    [System.Windows.MessageBox]::Show(
        $text,
        $messages.title,
        [System.Windows.MessageBoxButton]::OK,
        [System.Windows.MessageBoxImage]::Information
    ) | Out-Null
}

function Confirm-Action([string]$text) {
    if ($Silent) { return $false }
    $answer = [System.Windows.MessageBox]::Show(
        $text,
        $messages.title,
        [System.Windows.MessageBoxButton]::YesNo,
        [System.Windows.MessageBoxImage]::Question
    )
    return $answer -eq [System.Windows.MessageBoxResult]::Yes
}

# 记录文件丢了（比如上次启动中途失败），仍然要能把服务停掉，
# 否则端口一直被占着，下次启动只会报「文件正由另一进程使用」。
# 按端口反查进程，并且**一定先问过用户**再动手——
# 万一 8766 被别的程序占用，不能默默杀掉人家。
function Find-ServerByPort {
    try {
        $listener = Get-NetTCPConnection -State Listen -LocalPort $appPort -ErrorAction Stop |
            Select-Object -First 1
    } catch {
        return $null
    }
    if (-not $listener) { return $null }
    return Get-Process -Id $listener.OwningProcess -ErrorAction SilentlyContinue
}

function Show-ErrorMessage([string]$text) {
    if ($Silent) {
        Write-Output $text
        return
    }
    [System.Windows.MessageBox]::Show(
        $text,
        $messages.title,
        [System.Windows.MessageBoxButton]::OK,
        [System.Windows.MessageBoxImage]::Error
    ) | Out-Null
}

try {
    if (-not (Test-Path $pidFile)) {
        $orphan = Find-ServerByPort
        if (-not $orphan) {
            Show-Info $messages.notRunning
            exit 0
        }
        $detail = "端口 $appPort 上还有一个进程在监听，但启动记录已经丢失。`n`n" +
                  "进程 ID：$($orphan.Id)`n程序：$($orphan.Path)`n`n" +
                  "确定要结束它吗？"
        if (-not (Confirm-Action $detail)) {
            Show-Info "已取消，没有结束任何进程。"
            exit 0
        }
        Stop-Process -Id $orphan.Id -Force
        $orphan.WaitForExit(5000) | Out-Null
        Show-Info $messages.stopped
        exit 0
    }

    $record = Get-Content -Raw -Encoding UTF8 $pidFile | ConvertFrom-Json
    $process = Get-Process -Id ([int]$record.pid) -ErrorAction SilentlyContinue

    if (-not $process) {
        Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
        Show-Info $messages.notRunning
        exit 0
    }

    $actualStart = $process.StartTime.ToUniversalTime()
    $recordedStart = [datetime]::Parse($record.startTimeUtc).ToUniversalTime()
    if ([math]::Abs(($actualStart - $recordedStart).TotalSeconds) -gt 2) {
        Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
        Show-Info $messages.notRunning
        exit 0
    }

    Stop-Process -Id $process.Id -Force
    $process.WaitForExit(5000) | Out-Null
    Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
    Show-Info $messages.stopped
}
catch {
    Show-ErrorMessage ($messages.stopFailed + $_.Exception.Message)
    exit 1
}
