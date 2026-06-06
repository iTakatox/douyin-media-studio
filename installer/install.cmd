@echo off
setlocal

set "APPDIR=%LOCALAPPDATA%\Programs\DouyinMediaStudio"

echo Installing Douyin Media Studio...
if not exist "%APPDIR%" mkdir "%APPDIR%"

powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -LiteralPath '%~dp0payload.zip' -DestinationPath '%APPDIR%' -Force"
if errorlevel 1 goto failed

cd /d "%APPDIR%"
powershell -NoProfile -ExecutionPolicy Bypass -File ".\setup.ps1"
if errorlevel 1 goto failed

start "" "%APPDIR%\start-desktop.bat"
echo Install complete.
exit /b 0

:failed
echo Install failed.
pause
exit /b 1
