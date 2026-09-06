param(
    [ValidateRange(1024, 65535)][int]$Port = 8765,
    [switch]$NoBrowser
)
$ErrorActionPreference = 'Stop'
$repository = Split-Path -Parent $PSScriptRoot
$address = "http://127.0.0.1:$Port"

function Get-PlaygroundStatus {
    try { return Invoke-RestMethod -Uri "$address/api/status" -TimeoutSec 2 }
    catch { return $null }
}

$status = Get-PlaygroundStatus
if ($null -eq $status) {
    $pythonCommand = (Get-Command python -ErrorAction Stop).Source
    $logDirectory = Join-Path $repository 'build/playground-logs'
    New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $serverPath = Join-Path $PSScriptRoot 'server.py'
    $serverArguments = @('-u', ('"' + $serverPath + '"'), '--port', $Port)
    $serverProcess = Start-Process -FilePath $pythonCommand -ArgumentList $serverArguments `
        -WorkingDirectory $repository -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $logDirectory "$stamp-out.log") `
        -RedirectStandardError (Join-Path $logDirectory "$stamp-error.log")
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        Start-Sleep -Milliseconds 250
        $serverProcess.Refresh()
        if ($serverProcess.HasExited) { throw "The playground server exited. Check $logDirectory." }
        $status = Get-PlaygroundStatus
        if ($null -ne $status) { break }
    }
}
if ($null -eq $status -or $null -eq $status.engine_ready -or $null -eq $status.capabilities) {
    throw "The Banjo playground did not respond at $address. Check whether another service is using this port."
}
Write-Output "Banjo playground: $address"
Write-Output "Engine ready: $($status.engine_ready); native studio ready: $($status.studio_ready); GPT key configured: $($status.key_configured)"
if (-not $NoBrowser) { Start-Process $address }
