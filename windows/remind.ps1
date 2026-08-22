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

$ErrorActionPreference = "Stop"
$appUrl = $Url

function Show-Toast([string]$title, [string]$body) {
    # Win10/11 自带的 WinRT 接口，不依赖任何需要额外安装的模块。
    # AppId 借用 PowerShell 自己的注册项——这是不注册应用也能弹通知的标准做法。
    [void][Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]
    [void][Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom, ContentType = WindowsRuntime]

    $xml = "<toast><visual><binding template=`"ToastGeneric`"><text>$title</text><text>$body</text></binding></visual></toast>"
    $doc = New-Object Windows.Data.Xml.Dom.XmlDocument
    $doc.LoadXml($xml)
    $toast = New-Object Windows.UI.Notifications.ToastNotification $doc
    $appId = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
    [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($appId).Show($toast)
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
