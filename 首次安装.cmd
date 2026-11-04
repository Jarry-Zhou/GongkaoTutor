@echo off
chcp 65001 >nul
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-dependencies.ps1"
if errorlevel 1 (
  echo 安装未完成，请查看上面的提示。
) else (
  echo 安装完成。双击启动知序.cmd开始使用。
)
pause
