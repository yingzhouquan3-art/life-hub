param(
    [switch]$Test,
    # 换过端口的话在这里指过去，默认就是启动器用的那个地址
    [string]$Url = "http://127.0.0.1:8766"
)

# 每日提醒：只在你今天什么都没记的时候出声。
#
# 一个天天准点响的提醒，两周之内就会被无视。所以这里先问服务端一句
# 「今天记了东西没有」，记了就安静退出——没有理由的提醒只会训练人忽略它。
#
# 服务没在跑也安静退出：那多半说明你不在电脑前，弹通知给空房间看没有意义。
#
# 为什么用 NotifyIcon 而不是 WinRT 的 ToastNotification：
# 后者要求调用方的 AppUserModelID 已经在系统里注册过。没注册时它
# **既不报错也不显示**——脚本退出码 0，用户什么都没看到。第一版就是这么
# 悄悄失败的。NotifyIcon 会自己生成并注册一个 AUMID（注册表里那些
# NotifyIconGeneratedAumid_* 就是它留下的），不依赖任何前置注册。

$ErrorActionPreference = "Stop"
$appUrl = $Url

function Show-Toast([string]$title, [string]$body) {
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing

    $icon = New-Object System.Windows.Forms.NotifyIcon
    try {
        $icon.Icon = [System.Drawing.SystemIcons]::Information
        $icon.Visible = $true
        $icon.BalloonTipTitle = $title
        $icon.BalloonTipText = $body
        $icon.BalloonTipIcon = [System.Windows.Forms.ToolTipIcon]::Info
        $icon.ShowBalloonTip(15000)
        # 托盘图标活着的时候通知才会留在屏幕上，太早退出会被一起收走
        Start-Sleep -Seconds 8
    }
    finally {
        $icon.Visible = $false
        $icon.Dispose()
    }
}

if ($Test) {
    Show-Toast "我的生活中枢" "这是一条测试通知。真正的提醒只在你今天还没记东西时才出现。"
    Write-Output "已发送测试通知"
    exit 0
}

try {
    $overview = Invoke-RestMethod -Uri "$appUrl/api/life/overview" -TimeoutSec 4
} catch {
    exit 0
}

if ($overview.completed_signals -gt 0) {
    exit 0
}

Show-Toast "我的生活中枢" "今天还没有任何记录。一句话就够：午饭 16.5 / 跑步 30 分钟 / 睡了 7 小时"
