$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

$email = (Read-Host "请输入已验证的 NASA PPS 注册邮箱").Trim().ToLowerInvariant()
if ([string]::IsNullOrWhiteSpace($email)) {
    Write-Host "未输入邮箱，下载未开始。" -ForegroundColor Yellow
    Read-Host "按 Enter 关闭窗口"
    exit 1
}

$logDirectory = Join-Path $projectRoot "outputs"
New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
$logPath = Join-Path $logDirectory "imerg_download.log"

$env:PPS_EMAIL = $email
$env:PYTHONPATH = Join-Path $projectRoot "src"
try {
    & python scripts/download_imerg_daily.py --download 2>&1 |
        Tee-Object -FilePath $logPath
    $downloadExitCode = $LASTEXITCODE
}
finally {
    Remove-Item Env:PPS_EMAIL -ErrorAction SilentlyContinue
}

if ($downloadExitCode -eq 0) {
    Write-Host "IMERG 下载与校验完成。" -ForegroundColor Green
}
else {
    Write-Host "IMERG 下载未完成，退出码：$downloadExitCode" -ForegroundColor Red
    Write-Host "日志：$logPath"
}
Read-Host "按 Enter 关闭窗口"
exit $downloadExitCode
