$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$WorkspaceRoot = Split-Path -Parent $ProjectRoot
$DownloaderDir = if ($env:DOUYIN_DOWNLOADER_DIR) {
    $env:DOUYIN_DOWNLOADER_DIR
}
else {
    Join-Path $WorkspaceRoot "douyin-downloader"
}

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python was not found. Install Python 3.11 or newer and enable Add Python to PATH."
}
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "Git was not found. Install Git for Windows and restart the application."
}

Write-Output "Checking downloader components..."
if ((Test-Path -LiteralPath $DownloaderDir) -and -not (Test-Path -LiteralPath (Join-Path $DownloaderDir "requirements.txt"))) {
    Write-Output "Removing an incomplete previous installation..."
    Remove-Item -LiteralPath $DownloaderDir -Recurse -Force
}
if (-not (Test-Path -LiteralPath $DownloaderDir)) {
    Write-Output "Downloading the Douyin downloader..."
    git clone --depth 1 https://github.com/jiji262/douyin-downloader.git $DownloaderDir
    if ($LASTEXITCODE -ne 0) {
        throw "Git clone failed with exit code $LASTEXITCODE."
    }
}

Push-Location $DownloaderDir
try {
    if (-not (Test-Path -LiteralPath ".\.venv\Scripts\python.exe")) {
        Write-Output "Creating the Python environment..."
        python -m venv .venv
        if ($LASTEXITCODE -ne 0) {
            throw "Python environment creation failed with exit code $LASTEXITCODE."
        }
    }

    Write-Output "Installing Python dependencies..."
    .\.venv\Scripts\python.exe -m pip install --disable-pip-version-check -r requirements.txt
    if ($LASTEXITCODE -ne 0) {
        throw "Dependency installation failed with exit code $LASTEXITCODE."
    }

    .\.venv\Scripts\python.exe -m pip install --disable-pip-version-check playwright
    if ($LASTEXITCODE -ne 0) {
        throw "Playwright installation failed with exit code $LASTEXITCODE."
    }

    Write-Output "Installing the multi-platform media engine..."
    .\.venv\Scripts\python.exe -m pip install --disable-pip-version-check --upgrade yt-dlp
    if ($LASTEXITCODE -ne 0) {
        throw "Multi-platform engine installation failed with exit code $LASTEXITCODE."
    }

    Write-Output "Installing optional Weibo and gallery engines..."
    .\.venv\Scripts\python.exe -m pip install --disable-pip-version-check --upgrade gallery-dl weibo-downloader
    if ($LASTEXITCODE -ne 0) {
        Write-Output "Optional engines were not installed. Core media download remains available."
    }

    Write-Output "Installing the login browser..."
    .\.venv\Scripts\python.exe -m playwright install chromium
    if ($LASTEXITCODE -ne 0) {
        throw "Chromium installation failed with exit code $LASTEXITCODE."
    }

    if (-not (Test-Path -LiteralPath ".\config.yml")) {
        Copy-Item -LiteralPath ".\config.example.yml" -Destination ".\config.yml"
    }
}
finally {
    Pop-Location
}

Write-Output "Downloader components are ready."
