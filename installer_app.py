import os
import subprocess
import sys
import zipfile
from pathlib import Path


APP_NAME = "DouyinMediaStudio"
INSTALL_DIR = Path(os.environ["LOCALAPPDATA"]) / "Programs" / "DouyinMediaStudio"


def resource_path(name):
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / name


def fail(message):
    print()
    print("Install failed:")
    print(message)
    input("Press Enter to close...")
    raise SystemExit(1)


def main():
    print("Douyin Media Studio Installer")
    print("=" * 32)
    print(f"Install directory: {INSTALL_DIR}")
    print()

    payload = resource_path("payload.zip")
    if not payload.exists():
        fail(f"Missing bundled payload: {payload}")

    INSTALL_DIR.mkdir(parents=True, exist_ok=True)
    print("Extracting application files...")
    with zipfile.ZipFile(payload, "r") as archive:
        archive.extractall(INSTALL_DIR)

    setup_script = INSTALL_DIR / "setup.ps1"
    if not setup_script.exists():
        fail(f"Missing setup script: {setup_script}")

    print("Running setup. This may download dependencies on first install...")
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

    print()
    print("Install complete.")
    print("Launching Douyin Media Studio...")
    subprocess.Popen([str(INSTALL_DIR / "start-desktop.bat")], cwd=str(INSTALL_DIR), shell=True)
    print()
    input("Press Enter to close installer...")


if __name__ == "__main__":
    main()
