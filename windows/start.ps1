param(
    [switch]$Silent,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$dataDir = Join-Path $projectRoot "data"
$venvDir = Join-Path $projectRoot ".venv"
$venvPython = Join-Path $venvDir "Scripts\python.exe"
$requirements = Join-Path $projectRoot "backend\requirements.txt"
$pidFile = Join-Path $dataDir "server-process.json"
$launcherLog = Join-Path $dataDir "launcher.log"
$serverLog = Join-Path $dataDir "server.log"
$serverErrorLog = Join-Path $dataDir "server-error.log"
$appUrl = "http://127.0.0.1:8766"

New-Item -ItemType Directory -Path $dataDir -Force | Out-Null

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

function Test-AppServer {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri "$appUrl/api/state" -TimeoutSec 2
        return $response.StatusCode -eq 200
    }
    catch {
        return $false
    }
}

function Test-PythonCandidate([string]$executable, [string[]]$prefixArguments) {
    try {
        $versionCode = & $executable @prefixArguments -c "import sys; print(sys.version_info.major * 100 + sys.version_info.minor)" 2>$null
        return ($LASTEXITCODE -eq 0) -and ([int]$versionCode -ge 309)
    }
    catch {
        return $false
    }
}

function Test-VenvDependencies {
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & $venvPython -c "import fastapi, uvicorn, pydantic" 2>$null
        return $LASTEXITCODE -eq 0
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }
}

function Invoke-NativeLogged([string]$executable, [string[]]$arguments) {
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & $executable @arguments 2>&1 |
            Out-File -FilePath $launcherLog -Encoding UTF8 -Append
        return $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }
}

function Normalize-ProcessPath {
    # Some developer tools expose both Path and PATH. Windows PowerShell 5.1
    # passes them to Start-Process as duplicate dictionary keys and then fails.
    $environment = [Environment]::GetEnvironmentVariables("Process")
    $pathKeys = @($environment.Keys | Where-Object { $_ -ieq "Path" })
    if ($pathKeys.Count -le 1) {
        return
    }

    $pathValue = $null
    foreach ($key in $pathKeys) {
        if ($key -ceq "Path") {
            $pathValue = $environment[$key]
            break
        }
    }
    if (-not $pathValue) {
        $pathValue = $environment[$pathKeys[0]]
    }

    foreach ($key in $pathKeys) {
        [Environment]::SetEnvironmentVariable([string]$key, $null, "Process")
    }
    [Environment]::SetEnvironmentVariable("Path", $pathValue, "Process")
}

function Find-Python {
    $candidates = New-Object System.Collections.Generic.List[object]

    $pyLauncher = Get-Command "py.exe" -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        $candidates.Add([pscustomobject]@{ Executable = $pyLauncher.Source; PrefixArguments = @("-3") })
    }

    foreach ($commandName in @("python.exe", "python3.exe")) {
        $command = Get-Command $commandName -ErrorAction SilentlyContinue
        if ($command) {
            $candidates.Add([pscustomobject]@{ Executable = $command.Source; PrefixArguments = @() })
        }
    }

    $localPrograms = Join-Path $env:LOCALAPPDATA "Programs\Python"
    if (Test-Path $localPrograms) {
        Get-ChildItem -Path $localPrograms -Filter "python.exe" -Recurse -ErrorAction SilentlyContinue |
            ForEach-Object {
                $candidates.Add([pscustomobject]@{ Executable = $_.FullName; PrefixArguments = @() })
            }
    }

    # Codex Desktop includes a private Python runtime. It is a useful fallback on
    # this machine, while the launcher still works with a regular Python install.
    $codexPython = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
    if (Test-Path $codexPython) {
        $candidates.Add([pscustomobject]@{ Executable = $codexPython; PrefixArguments = @() })
    }

    foreach ($candidate in $candidates) {
        if (Test-PythonCandidate $candidate.Executable $candidate.PrefixArguments) {
            return $candidate
        }
    }

    return $null
}

$mutex = New-Object System.Threading.Mutex($false, "Local\WealthFreedomGuideLamp.Start")
$ownsMutex = $false

try {
    Normalize-ProcessPath
    $ownsMutex = $mutex.WaitOne(0)
    if (-not $ownsMutex) {
        Show-Info $messages.alreadyStarting
        exit 0
    }

    if (Test-AppServer) {
        if (-not $NoBrowser) {
            Start-Process $appUrl
        }
        exit 0
    }

    if (Test-Path $pidFile) {
        Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
    }

    if (-not (Test-Path $venvPython)) {
        Show-Info $messages.firstSetup
        $python = Find-Python
        if (-not $python) {
            Show-ErrorMessage $messages.pythonMissing
            if (-not $NoBrowser) {
                Start-Process "https://www.python.org/downloads/windows/"
            }
            exit 1
        }

        "[$(Get-Date -Format o)] Creating virtual environment with $($python.Executable)" |
            Out-File -FilePath $launcherLog -Encoding UTF8
        $venvArguments = @($python.PrefixArguments) + @("-m", "venv", $venvDir)
        $venvExitCode = Invoke-NativeLogged $python.Executable $venvArguments
        if (($venvExitCode -ne 0) -or (-not (Test-Path $venvPython))) {
            throw "Unable to create the local Python environment."
        }
    }

    if (-not (Test-VenvDependencies)) {
        Show-Info $messages.installingDependencies
        "[$(Get-Date -Format o)] Installing dependencies" |
            Out-File -FilePath $launcherLog -Encoding UTF8 -Append
        $pipExitCode = Invoke-NativeLogged $venvPython @(
            "-m", "pip", "install", "--disable-pip-version-check", "-r", $requirements
        )
        if ($pipExitCode -ne 0) {
            throw "Unable to install the required components. Check your network connection and try again."
        }
    }

    Set-Content -Path $serverLog -Value "" -Encoding UTF8
    Set-Content -Path $serverErrorLog -Value "" -Encoding UTF8

    # 默认只监听回环，手机连不进来但也没有任何暴露面。
    # 监听地址由 backend/core/access.py 的 resolve_bind_host 统一决定，
    # 这里不重复一份判断逻辑。LIFE_HUB_HOST 可以是：
    #   （不设）  只监听本机
    #   auto      有 Tailscale 用 Tailscale，否则用当前局域网
    #   lan       只用当前局域网（手机和电脑连同一个 WiFi）
    #   tailscale 只用 Tailscale
    #   具体地址   直接指定
    # 任何情况下找不到目标网络都会退回回环；0.0.0.0 会被明确拒绝。
    $hostPreference = $env:LIFE_HUB_HOST
    $resolved = & $venvPython -c "import json,sys;from backend.core.access import resolve_bind_host;
try:
    print(json.dumps(resolve_bind_host(sys.argv[1] if len(sys.argv)>1 else '')))
except ValueError as exc:
    print(json.dumps({'error': str(exc)}))" $hostPreference
    $binding = $resolved | ConvertFrom-Json
    if ($binding.error) { throw $binding.error }
    $bindHost = $binding.host
    Write-Host $binding.reason
    if ($binding.mode -ne "local") {
        Write-Host "手机配对页面：http://127.0.0.1:8766/pair.html"
    }

    $serverArguments = @(
        "-m", "uvicorn", "backend.main:app",
        "--host", $bindHost,
        "--port", "8766"
    )
    $serverProcess = Start-Process `
        -FilePath $venvPython `
        -ArgumentList $serverArguments `
        -WorkingDirectory $projectRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $serverLog `
        -RedirectStandardError $serverErrorLog `
        -PassThru

    $processRecord = [pscustomobject]@{
        pid = $serverProcess.Id
        startTimeUtc = $serverProcess.StartTime.ToUniversalTime().ToString("o")
    }
    $processRecord | ConvertTo-Json | Set-Content -Path $pidFile -Encoding UTF8

    $started = $false
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        Start-Sleep -Milliseconds 500
        if (Test-AppServer) {
            $started = $true
            break
        }
        if ($serverProcess.HasExited) {
            break
        }
    }

    if (-not $started) {
        if (-not $serverProcess.HasExited) {
            Stop-Process -Id $serverProcess.Id -Force -ErrorAction SilentlyContinue
        }
        Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
        $details = ""
        if (Test-Path $serverErrorLog) {
            $details = (Get-Content -Path $serverErrorLog -Tail 12 -ErrorAction SilentlyContinue) -join "`n"
        }
        Show-ErrorMessage ($messages.serverFailed + $details)
        exit 1
    }

    if (-not $NoBrowser) {
        Start-Process $appUrl
    }
}
catch {
    $_ | Out-String | Out-File -FilePath $launcherLog -Encoding UTF8 -Append
    Show-ErrorMessage ($messages.startupFailed + $_.Exception.Message)
    exit 1
}
finally {
    if ($ownsMutex) {
        $mutex.ReleaseMutex()
    }
    $mutex.Dispose()
}
