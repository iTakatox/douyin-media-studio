$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Desktop = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $Desktop "Douyin Media Studio.lnk"
$TargetPath = Join-Path $ProjectRoot "start-desktop.bat"
$IconPath = Join-Path $ProjectRoot "app.ico"

if (-not (Test-Path -LiteralPath $TargetPath)) {
    throw "Cannot find start-desktop.bat at $TargetPath"
}

$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $TargetPath
$Shortcut.WorkingDirectory = $ProjectRoot
if (Test-Path -LiteralPath $IconPath) {
    $Shortcut.IconLocation = $IconPath
}
$Shortcut.Save()

Write-Host "Desktop shortcut created:"
Write-Host $ShortcutPath
