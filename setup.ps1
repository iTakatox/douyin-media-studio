$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$WorkspaceRoot = Split-Path -Parent $ProjectRoot
$DownloaderDir = Join-Path $WorkspaceRoot "douyin-downloader"

Write-Host "Installing Douyin Media Studio..."

if (-not (Test-Path -LiteralPath $DownloaderDir)) {
    Write-Host "Cloning douyin-downloader..."
    git clone https://github.com/jiji262/douyin-downloader.git $DownloaderDir
}

Push-Location $DownloaderDir
try {
    if (-not (Test-Path -LiteralPath ".\.venv\Scripts\python.exe")) {
        python -m venv .venv
    }
    .\.venv\Scripts\python.exe -m pip install -r requirements.txt
    .\.venv\Scripts\python.exe -m pip install playwright
    .\.venv\Scripts\python.exe -m playwright install chromium

    if (-not (Test-Path -LiteralPath ".\config.yml")) {
        Copy-Item -LiteralPath ".\config.example.yml" -Destination ".\config.yml"
    }
}
finally {
    Pop-Location
}

python -m pip install -r (Join-Path $ProjectRoot "requirements.txt")

$Desktop = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $Desktop "Douyin Media Studio.lnk"
$TargetPath = Join-Path $ProjectRoot "start-desktop.bat"
$IconPath = Join-Path $ProjectRoot "app.ico"

$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $TargetPath
$Shortcut.WorkingDirectory = $ProjectRoot
if (Test-Path -LiteralPath $IconPath) {
    $Shortcut.IconLocation = $IconPath
}
$Shortcut.Save()

Write-Host ""
Write-Host "Setup complete."
Write-Host "Desktop shortcut created: $ShortcutPath"
Write-Host "Double-click 'Douyin Media Studio' on your desktop to start."
