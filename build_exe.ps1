# Builds DJMixStudio.exe (onedir) with PyInstaller.
# Run from the project root: powershell -ExecutionPolicy Bypass -File build_exe.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

pyinstaller desktop_app.py `
  --name DJMixStudio `
  --noconfirm `
  --icon frontend/app.ico `
  --paths backend `
  --add-data "frontend;frontend" `
  --add-data "backend/data/sample_library;backend/data/sample_library" `
  --collect-all librosa `
  --collect-all numba `
  --collect-all llvmlite `
  --collect-all soundfile `
  --collect-all webview `
  --collect-all sklearn `
  --collect-all scipy `
  --collect-all uvicorn `
  --collect-all fastapi `
  --collect-all starlette `
  --hidden-import main `
  --hidden-import engine `
  --hidden-import engine.render `
  --hidden-import engine.effects `
  --hidden-import engine.envelope `
  --hidden-import models `
  --hidden-import library `
  --hidden-import analysis `
  --hidden-import storage `
  --exclude-module torch `
  --exclude-module torchvision `
  --exclude-module torchaudio `
  --exclude-module tensorflow `
  --exclude-module tensorboard `
  --exclude-module pandas `
  --exclude-module pyarrow `
  --exclude-module matplotlib `
  --exclude-module IPython `
  --exclude-module notebook

Write-Host "`nBuild output: $PSScriptRoot\dist\DJMixStudio\DJMixStudio.exe"
