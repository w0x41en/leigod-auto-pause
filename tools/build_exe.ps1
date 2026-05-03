# Build standalone Windows executable for LeiGod Auto Pause.
# Usage:
#   powershell -ExecutionPolicy Bypass -File .\tools\build_exe.ps1

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

python -m pip install -r requirements.txt
python -m pip install pyinstaller
python -m PyInstaller --clean .\leigod_wrapper.spec

New-Item -ItemType Directory -Force -Path .\release | Out-Null
Copy-Item .\dist\leigod_wrapper.exe .\release\leigod_wrapper.exe -Force
Copy-Item .\config\leigod_config.example.yaml .\release\leigod_config.yaml -Force

Write-Host "Built: $Root\release\leigod_wrapper.exe"
