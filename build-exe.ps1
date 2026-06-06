$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $ProjectRoot
try {
    python -m pip install pyinstaller -r requirements.txt
    pyinstaller --noconfirm --onefile --name DouyinMediaStudio app.py
    Write-Host "EXE created under dist\DouyinMediaStudio.exe"
}
finally {
    Pop-Location
}
