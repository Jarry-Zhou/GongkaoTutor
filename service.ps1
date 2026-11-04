param(
    [ValidateSet('start','stop','status')][string]$Action = 'start',
    [ValidateRange(1024,65535)][int]$Port = 8765
)
$ErrorActionPreference = 'Stop'
$taskRoot = $PSScriptRoot
$taskWork = Join-Path $taskRoot 'work'
$taskStem = if ($Port -eq 8765) { 'server' } else { "server-$Port" }
$taskPidFile = Join-Path $taskWork "$taskStem.pid"
$taskUrl = "http://127.0.0.1:$Port"
if ($Action -eq 'status') {
    try { $status = Invoke-RestMethod "$taskUrl/api/health" -TimeoutSec 2; Write-Output $status }
    catch { Write-Output '服务未运行。' }
    exit
}
if ($Action -eq 'stop') {
    if (Test-Path -LiteralPath $taskPidFile) {
        $taskServerPid = [int](Get-Content -LiteralPath $taskPidFile)
        $taskProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $taskServerPid"
        $taskAppPath = Join-Path $taskRoot 'app.py'
        if ($taskProcess -and $taskProcess.CommandLine.Contains($taskAppPath)) {
            Stop-Process -Id $taskServerPid
            Remove-Item -LiteralPath $taskPidFile
            Write-Output '知序服务已停止，学习记录已保留。'
        } else { Write-Output '未找到匹配的知序进程，未执行停止。' }
    } else { Write-Output '没有本项目的运行记录。' }
    exit
}
try {
    $taskExisting = Invoke-RestMethod "$taskUrl/api/health" -TimeoutSec 2
    if ($taskExisting.application_id -eq 'gongkao-tutor') { Write-Output "知序已在运行：$taskUrl"; exit }
    throw "端口 $Port 已被其他应用使用。"
} catch {
    if ($_.Exception.Message -eq "端口 $Port 已被其他应用使用。") { throw }
}
New-Item -ItemType Directory -Path $taskWork -Force | Out-Null
$taskVenvPython = Join-Path $taskRoot '.venv\Scripts\python.exe'
if (Test-Path -LiteralPath $taskVenvPython) { $taskPython = $taskVenvPython }
elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $taskPython = (& py -3 -c 'import sys; print(sys.executable)')
    if ($LASTEXITCODE -ne 0) { throw '未找到可用的 Python，请先安装 Python 3.11 或以上版本。' }
    $taskPython = $taskPython.Trim()
}
elseif (Get-Command python -ErrorAction SilentlyContinue) { $taskPython = (Get-Command python).Source }
else { throw '请先安装 Python 3.11 或以上版本，并运行首次安装.cmd。' }
& $taskPython -c 'import sys; assert sys.version_info >= (3,11), "Python 3.11+ required"'
if ($LASTEXITCODE -ne 0) { throw 'Python 版本不符合要求，请使用 Python 3.11 或以上版本。' }
$taskAppPath = Join-Path $taskRoot 'app.py'
$taskProcess = Start-Process -FilePath $taskPython -ArgumentList @('-u',('"' + $taskAppPath + '"'),'--port',[string]$Port) -WorkingDirectory $taskRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $taskWork "$taskStem.out.log") -RedirectStandardError (Join-Path $taskWork "$taskStem.err.log") -PassThru
$taskProcess.Id | Set-Content -LiteralPath $taskPidFile
for ($taskAttempt = 0; $taskAttempt -lt 30; $taskAttempt++) {
    Start-Sleep -Milliseconds 200
    try {
        $taskStatus = Invoke-RestMethod "$taskUrl/api/health" -TimeoutSec 1
        if ($taskStatus.application_id -eq 'gongkao-tutor') { Write-Output "知序已启动：$taskUrl"; exit }
    } catch { }
}
throw "启动未完成，请查看 work/$taskStem.err.log。"
