$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$taskVenv = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskVenv)) {
    if (Get-Command py -ErrorAction SilentlyContinue) { & py -3 -m venv .venv }
    elseif (Get-Command python -ErrorAction SilentlyContinue) { & python -m venv .venv }
    else { throw '未找到 Python。请先安装 Python 3.11 或以上版本，并选择加入 PATH。' }
    if ($LASTEXITCODE -ne 0) { throw '无法创建项目环境，请检查 Python 安装及目录写入权限。' }
}
& $taskVenv -c 'import sys; assert sys.version_info >= (3,11), "Python 3.11+ required"'
if ($LASTEXITCODE -ne 0) { throw '请使用 Python 3.11 或以上版本。' }
& $taskVenv -m pip install -r (Join-Path $PSScriptRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw '依赖安装未完成，请检查网络和安装输出。' }
& $taskVenv -c "import local_ocr; assert local_ocr.status()['available'], 'OCR models missing'; print('Local OCR ready')"
if ($LASTEXITCODE -ne 0) { throw 'OCR 模型检查未通过。' }
Write-Host '文档导入和本地中文 OCR 已安装，请重新启动知序。'
