import os
import subprocess
import sys
import zipfile
from pathlib import Path


APP_NAME = "DouyinMediaStudio"
INSTALL_DIR = Path(os.environ["LOCALAPPDATA"]) / "Programs" / "DouyinMediaStudio"
LOG_PATH = INSTALL_DIR / "install.log"


def resource_path(name):
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / name


def fail(message):
    print()
    print("Install failed:")
    print(message)
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as log:
            log.write(f"FAILED: {message}\n")
    except OSError:
        pass
    input("Press Enter to close...")
    raise SystemExit(1)


def log(message):
    print(message)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(message + "\n")


def create_desktop_shortcut():
    shortcut_script = f"""
$Desktop = [Environment]::GetFolderPath('Desktop')
$ShortcutPath = Join-Path $Desktop 'Douyin Media Studio.lnk'
$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = '{str(INSTALL_DIR / "start-desktop.bat")}'
$Shortcut.WorkingDirectory = '{str(INSTALL_DIR)}'
$IconPath = '{str(INSTALL_DIR / "app.ico")}'
if (Test-Path -LiteralPath $IconPath) {{ $Shortcut.IconLocation = $IconPath }}
$Shortcut.Save()
Write-Output $ShortcutPath
"""
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", shortcut_script],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Desktop shortcut creation failed.")
    return result.stdout.strip()


def main():
    log("Douyin Media Studio Installer")
    log("=" * 32)
    log(f"Install directory: {INSTALL_DIR}")

    payload = resource_path("payload.zip")
    if not payload.exists():
        fail(f"Missing bundled payload: {payload}")

    INSTALL_DIR.mkdir(parents=True, exist_ok=True)
    log("Extracting application files...")
    with zipfile.ZipFile(payload, "r") as archive:
        archive.extractall(INSTALL_DIR)

    try:
        shortcut = create_desktop_shortcut()
        log(f"Desktop shortcut created: {shortcut}")
    except Exception as exc:
        fail(f"Could not create desktop shortcut: {exc}")

    setup_script = INSTALL_DIR / "setup.ps1"
    if not setup_script.exists():
        fail(f"Missing setup script: {setup_script}")

    log("Running setup. This may download dependencies on first install...")
    command = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(setup_script),
    ]
    result = subprocess.run(command, cwd=str(INSTALL_DIR))
    if result.returncode != 0:
        fail(f"setup.ps1 exited with code {result.returncode}")

    log("Install complete.")
    log("Launching Douyin Media Studio...")
    subprocess.Popen([str(INSTALL_DIR / "start-desktop.bat")], cwd=str(INSTALL_DIR), shell=True)
    input("Press Enter to close installer...")


if __name__ == "__main__":
    main()
