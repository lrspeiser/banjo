param(
    [string]$BuildDirectory = "build/win-integration",
    [string]$OutputDirectory = ("build/assistant-check-" + (Get-Date -Format "yyyyMMdd-HHmmss")),
    [ValidateSet("glass", "oak", "iron", "door")]
    [string[]]$Cases = @("glass", "oak", "iron", "door")
)
$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$buildPath = Join-Path $repoRoot $BuildDirectory
$runPath = Join-Path $repoRoot $OutputDirectory
if (Test-Path -LiteralPath $runPath) { throw "Assistant evidence directory already exists; choose a fresh OutputDirectory" }
New-Item -ItemType Directory -Path $runPath | Out-Null
$runPath = (Resolve-Path -LiteralPath $runPath).Path
$creatorExe = Join-Path $buildPath "Release/banjo_creator_cli.exe"
$probeExe = Join-Path $buildPath "Release/banjo_assistant_probe.exe"
$fixtures = Join-Path $repoRoot "assets/creator/assistant"
$worldPath = Join-Path $runPath "start-world.json"
$collection = & $creatorExe --commands (Join-Path $fixtures "collect-materials.json") --save $worldPath
if ($LASTEXITCODE -ne 0) { throw "Initial inventory setup failed" }
if (@($collection | ConvertFrom-Json | Where-Object { -not $_.ok }).Count -ne 0) { throw "A collection command failed" }
foreach ($caseName in $Cases) {
    $requestId = "$caseName-check"
    $timer = [System.Diagnostics.Stopwatch]::StartNew()
    & $probeExe --world $worldPath --prompt-file (Join-Path $fixtures "$caseName.txt") --workspace $runPath --request-id $requestId --apply |
        Tee-Object -FilePath (Join-Path $runPath "$caseName.log")
    $probeExit = $LASTEXITCODE
    $timer.Stop()
    if ($probeExit -ne 0) { throw "Assistant case $caseName failed with code $probeExit" }
    $response = Get-Content -LiteralPath (Join-Path $runPath "assistant-$requestId/response.json") -Raw | ConvertFrom-Json
    if ($caseName -eq "door") {
        if ($response.status -ne "clarification" -or $null -ne $response.recipe) { throw "Unsupported door must yield a clarification" }
    } else {
        if ($response.status -ne "proposal" -or $response.recipe.material -ne $caseName -or $response.recipe.shape.radius_m -ne 0.06) {
            throw "Assistant did not preserve the requested material and diameter"
        }
    }
    [pscustomobject]@{case = $caseName; elapsed_seconds = $timer.Elapsed.TotalSeconds; status = $response.status} |
        ConvertTo-Json | Set-Content -LiteralPath (Join-Path $runPath "$caseName-timing.json") -Encoding utf8
}
Write-Output "Assistant evidence saved in $runPath"
