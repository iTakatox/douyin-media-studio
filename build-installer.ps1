$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ReleaseDir = Join-Path $ProjectRoot "release"
$WorkDir = Join-Path $env:TEMP "DouyinMediaStudioInstallerBuild"
$PayloadZip = Join-Path $WorkDir "payload.zip"
$InstallerExe = Join-Path $WorkDir "DouyinMediaStudioSetup-v1.2.0.exe"
$FinalInstallerExe = Join-Path $ReleaseDir "DouyinMediaStudioSetup-v1.2.0.exe"
$SedPath = Join-Path $WorkDir "installer.sed"

New-Item -ItemType Directory -Path $ReleaseDir -Force | Out-Null
if (Test-Path -LiteralPath $WorkDir) {
    Remove-Item -LiteralPath $WorkDir -Recurse -Force
}
New-Item -ItemType Directory -Path $WorkDir -Force | Out-Null

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
    Compress-Archive -Path $PayloadItems -DestinationPath $PayloadZip -Force
}
finally {
    Pop-Location
}

Copy-Item -LiteralPath (Join-Path $ProjectRoot "installer\install.cmd") -Destination (Join-Path $WorkDir "install.cmd") -Force

$sed = @"
[Version]
Class=IEXPRESS
SEDVersion=3
[Options]
PackagePurpose=InstallApp
ShowInstallProgramWindow=1
HideExtractAnimation=1
UseLongFileName=1
InsideCompressed=0
CAB_FixedSize=0
CAB_ResvCodeSigning=0
RebootMode=N
InstallPrompt=
DisplayLicense=
FinishMessage=
TargetName=$InstallerExe
FriendlyName=Douyin Media Studio Setup
AppLaunched=install.cmd
PostInstallCmd=<None>
AdminQuietInstCmd=
UserQuietInstCmd=
SourceFiles=SourceFiles
[Strings]
FILE0="install.cmd"
FILE1="payload.zip"
[SourceFiles]
SourceFiles0=$WorkDir
[SourceFiles0]
%FILE0%=
%FILE1%=
"@

Set-Content -LiteralPath $SedPath -Value $sed -Encoding ASCII
iexpress.exe /N /Q $SedPath

$deadline = (Get-Date).AddSeconds(30)
while (-not (Test-Path -LiteralPath $InstallerExe)) {
    if ((Get-Date) -gt $deadline) {
        throw "Installer was not created: $InstallerExe"
    }
    Start-Sleep -Milliseconds 250
}

Copy-Item -LiteralPath $InstallerExe -Destination $FinalInstallerExe -Force
Get-Item -LiteralPath $FinalInstallerExe
