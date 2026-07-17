$ErrorActionPreference = "Stop"
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

$secureEmail = Read-Host "请输入已验证的 NASA PPS 注册邮箱（输入不会回显）" -AsSecureString
$email = ([System.Net.NetworkCredential]::new("", $secureEmail).Password).Trim().ToLowerInvariant()
if ([string]::IsNullOrWhiteSpace($email)) {
    Write-Host "未输入邮箱，下载未开始。" -ForegroundColor Yellow
    Read-Host "按 Enter 关闭窗口"
    exit 1
}

$logDirectory = Join-Path $projectRoot "outputs"
New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
$logPath = Join-Path $logDirectory "imerg_independent_download.log"

$env:PPS_EMAIL = $email
$env:PYTHONPATH = Join-Path $projectRoot "src"
try {
    & python scripts/download_imerg_daily.py `
        --coverage-gaps manifests/independent_heavy_rain_observation_gaps.csv `
        --allowed-split independent_test `
        --frozen-rule configs/heavy_rain_rules_v2.yaml `
        --plan configs/imerg_independent_heavy_rain_gap_plan.csv `
        --download `
        --manifest outputs/imerg_independent_download_manifest.csv 2>&1 |
        Tee-Object -FilePath $logPath
    $downloadExitCode = $LASTEXITCODE
}
finally {
    Remove-Item Env:PPS_EMAIL -ErrorAction SilentlyContinue
    Remove-Item Env:PPS_PASSWORD -ErrorAction SilentlyContinue
}

if ($downloadExitCode -eq 0) {
    Write-Host "4个独立暴雨IMERG日文件下载并校验完成。" -ForegroundColor Green
}
else {
    Write-Host "下载未完成，退出码：$downloadExitCode" -ForegroundColor Red
    Write-Host "日志：$logPath"
}
Read-Host "按 Enter 关闭窗口"
exit $downloadExitCode
