param(
    [ValidateSet('init','setup','prepare','start','check','status')]
    [string]$Action = 'start',
    [string]$PythonPath,
    [string]$DownloadProxy
)
$ErrorActionPreference = 'Stop'
if ($PythonPath) {
    $pythonExe = $PythonPath
    $pythonArgs = @()
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $pythonExe = 'py'
    $pythonArgs = @('-3')
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $pythonExe = 'python'
    $pythonArgs = @()
} else {
    throw 'Install Python 3.10+ first, or provide -PythonPath.'
}
$scriptArgs = @('-B', (Join-Path $PSScriptRoot 'jlu_shadowrocket.py'), $Action)
if ($DownloadProxy) { $scriptArgs += @('--download-proxy', $DownloadProxy) }
& $pythonExe @pythonArgs @scriptArgs
exit $LASTEXITCODE
