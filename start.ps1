$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
Write-Host '知序 · 本地公考学习工作台' -ForegroundColor Green
& (Join-Path $PSScriptRoot 'service.ps1') -Action start
Start-Process 'http://127.0.0.1:8765'
Write-Host '已打开浏览器。使用“停止知序.cmd”可以停止本地服务。'
