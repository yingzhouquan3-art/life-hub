param(
    [switch]$Silent
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$dataDir = Join-Path $projectRoot "data"
$pidFile = Join-Path $dataDir "server-process.json"
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
        Show-Info $messages.notRunning
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
