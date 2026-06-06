$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ReleaseDir = Join-Path $ProjectRoot "release"
$PayloadZip = Join-Path $ReleaseDir "payload-v1.2.1.zip"
$InstallerExe = Join-Path $ReleaseDir "DouyinMediaStudioSetup-v1.2.1.exe"

New-Item -ItemType Directory -Path $ReleaseDir -Force | Out-Null

$PayloadItems = @(
    "app.py",
    "desktop_app.py",
    "app.ico",
    "README.md",
    "requirements.txt",
    "setup.ps1",
    "start-desktop.bat",
    "start-web.bat",
    "build-exe.ps1",
    "static",
    "templates"
)

Push-Location $ProjectRoot
try {
    if (Test-Path -LiteralPath $PayloadZip) {
        Remove-Item -LiteralPath $PayloadZip -Force
    }
    Compress-Archive -Path $PayloadItems -DestinationPath $PayloadZip -Force

    python -m PyInstaller --noconfirm --onefile --console `
        --name DouyinMediaStudioSetup-v1.2.1 `
        --icon app.ico `
        --add-data "$PayloadZip;." `
        installer_app.py

    Copy-Item -LiteralPath ".\dist\DouyinMediaStudioSetup-v1.2.1.exe" -Destination $InstallerExe -Force
    Get-Item -LiteralPath $InstallerExe
}
finally {
    Pop-Location
}
