# 放行手机访问所需的入站端口。
#
# 这个脚本会修改 Windows 防火墙设置，所以必须以管理员身份运行。
# 它只做两件事，都会先告诉你再做：
#   1. 加一条只针对「专用网络」的入站放行规则；
#   2. 如果当前网络被归为「公用」，问你要不要改成「专用」——
#      不改的话第 1 步加的规则不会生效。
#
# 不会改动任何其他防火墙设置，也不会关闭防火墙。

param(
    [int]$Port = 8766
)

$ErrorActionPreference = "Stop"
$ruleName = "我的生活中枢 $Port"

function Test-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-Administrator)) {
    # 自己把自己以管理员身份重开一次。
    # 提权放在这里而不是 .cmd 里：中文路径经过 cmd 再转一层字符串很容易出错，
    # PowerShell 用 -File 传路径不受代码页影响。
    Write-Host ""
    Write-Host "  需要管理员权限，正在申请……请在弹出的系统提示里点「是」。" -ForegroundColor Yellow
    try {
        Start-Process powershell.exe -Verb RunAs -ArgumentList @(
            "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $PSCommandPath, "-Port", $Port
        ) | Out-Null
    } catch {
        Write-Host ""
        Write-Host "  没有获得管理员权限，什么都没有改动。" -ForegroundColor Yellow
        Write-Host "  可以右键这个文件选「以管理员身份运行」，或者手动执行："
        Write-Host ""
        Write-Host "    New-NetFirewallRule -DisplayName '我的生活中枢 $Port' -Direction Inbound -Action Allow -Protocol TCP -LocalPort $Port -Profile Private"
        Write-Host ""
        Read-Host "  按回车关闭"
    }
    exit 0
}

Write-Host ""
Write-Host "  放行手机访问 · 端口 $Port" -ForegroundColor Cyan
Write-Host ""

# ---------- 1. 防火墙规则 ----------
$existing = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "  规则已存在，先删掉旧的再重建，避免出现重复条目。"
    $existing | Remove-NetFirewallRule
}

New-NetFirewallRule `
    -DisplayName $ruleName `
    -Description "允许同一局域网内的手机访问「我的生活中枢」。仅限专用网络。" `
    -Direction Inbound `
    -Action Allow `
    -Protocol TCP `
    -LocalPort $Port `
    -Profile Private | Out-Null

Write-Host "  [完成] 已放行 TCP $Port（仅专用网络）" -ForegroundColor Green

# ---------- 2. 网络类型 ----------
$profiles = Get-NetConnectionProfile | Where-Object { $_.IPv4Connectivity -ne "Disconnected" }
$public = @($profiles | Where-Object { $_.NetworkCategory -eq "Public" })

if ($public.Count -eq 0) {
    Write-Host "  [完成] 当前网络已经是专用网络，规则可以生效" -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "  注意：当前网络被 Windows 归为「公用网络」，" -ForegroundColor Yellow
    Write-Host "  上面这条规则在公用网络下不会生效，手机仍然连不上。"
    Write-Host ""
    foreach ($item in $public) {
        Write-Host "    网络：$($item.Name)（$($item.InterfaceAlias)）"
    }
    Write-Host ""
    Write-Host "  改成「专用网络」意味着这台电脑在这个网络里可被发现。"
    Write-Host "  只在你信任的网络上这么做，比如自己家的 WiFi 或自己手机的热点。"
    Write-Host ""
    $answer = Read-Host "  把上面这些网络改成专用网络？(y/N)"
    if ($answer -eq "y" -or $answer -eq "Y") {
        foreach ($item in $public) {
            Set-NetConnectionProfile -InterfaceIndex $item.InterfaceIndex -NetworkCategory Private
            Write-Host "  [完成] $($item.Name) 已改为专用网络" -ForegroundColor Green
        }
    } else {
        Write-Host "  已跳过。手机大概率仍然连不上，可以随时重新运行这个脚本。" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "  接下来：" -ForegroundColor Cyan
Write-Host "    1. 双击「启动并允许手机访问.cmd」启动服务"
Write-Host "    2. 在打开的配对页面点「重新检查」，四项应当全部变成 ✓"
Write-Host "    3. 把带 token 的地址发到手机上打开"
Write-Host ""
Read-Host "  按回车关闭"
