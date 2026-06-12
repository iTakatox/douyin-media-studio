$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$WorkspaceRoot = Split-Path -Parent $ProjectRoot
$DownloaderDir = if ($env:DOUYIN_DOWNLOADER_DIR) { $env:DOUYIN_DOWNLOADER_DIR } else { Join-Path $WorkspaceRoot "douyin-downloader" }

Write-Output "检查下载组件..."
if (-not (Test-Path -LiteralPath $DownloaderDir)) {
    git clone --depth 1 https://github.com/jiji262/douyin-downloader.git $DownloaderDir
}

Push-Location $DownloaderDir
try {
    if (-not (Test-Path -LiteralPath ".\.venv\Scripts\python.exe")) {
        python -m venv .venv
    }
    Write-Output "安装 Python 依赖..."
    .\.venv\Scripts\python.exe -m pip install --disable-pip-version-check -r requirements.txt
    .\.venv\Scripts\python.exe -m pip install --disable-pip-version-check playwright
    Write-Output "安装登录浏览器组件..."
    .\.venv\Scripts\python.exe -m playwright install chromium

    if (-not (Test-Path -LiteralPath ".\config.yml")) {
        Copy-Item -LiteralPath ".\config.example.yml" -Destination ".\config.yml"
    }
}
finally {
    Pop-Location
}

Write-Output "下载组件安装完成。"
