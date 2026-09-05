param(
    [string]$BuildDirectory = "build/win-integration",
    [double[]]$TimeSteps = @(0.0000125, 0.00000625, 0.000003125),
    [string]$OutputDirectory = "build/trajectory-matrix"
)
# Fixed geometry/law: only numerical time resolution changes. Retain all materials.
$ErrorActionPreference = "Stop"
$probe = (Resolve-Path -LiteralPath (Join-Path $BuildDirectory "Release/banjo_solver_probe.exe")).Path
$executableHash = (Get-FileHash -LiteralPath $probe -Algorithm SHA256).Hash.ToLowerInvariant()
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$destination = (Resolve-Path -LiteralPath $OutputDirectory).Path
$culture = [Globalization.CultureInfo]::InvariantCulture
$rates = foreach ($dt in $TimeSteps) {
    if ([double]::IsNaN($dt) -or [double]::IsInfinity($dt) -or $dt -le 0) { throw "Invalid timestep" }
    $steps = [Math]::Round(.005/$dt)
    $stride = [Math]::Round(.0001/$dt)
    if ($steps -lt 1 -or $steps -gt 100000 -or $stride -lt 1 -or
        [Math]::Abs($steps*$dt-.005) -gt 1e-12 -or [Math]::Abs($stride*$dt-.0001) -gt 1e-12) {
        throw "Each timestep must divide both 5 ms duration and 100 microsecond output spacing, within the probe step limit"
    }
    @{Dt=$dt.ToString("R",$culture); Steps=$steps.ToString("0",$culture); Stride=$stride.ToString("0",$culture)}
}
$commit = (& git rev-parse HEAD).Trim()
$dirty = [bool](& git status --porcelain)
$rows = @()
foreach ($material in @("glass","oak","iron")) {
    foreach ($damping in @("0","10000")) {
        foreach ($rate in $rates) {
            $name = "$material-c$damping-dt$($rate.Dt)"
            $trajectory = Join-Path $destination ($name+"-trajectory.csv")
            $log = Join-Path $destination ($name+".txt")
            $arguments = @("--material",$material,"--case","floor","--step-mode","compliant",
                "--voxel-size","0.04","--gap","0.001","--speed","1","--gravity","0",
                "--normal-stiffness","100000000","--normal-damping",$damping,"--max-compression","0.005",
                "--dt",$rate.Dt,"--steps",$rate.Steps,"--trajectory",$trajectory,"--sample-every",$rate.Stride)
            $started = [DateTime]::UtcNow
            $output = & $probe @arguments 2>&1
            $code = $LASTEXITCODE
            $output | Set-Content -LiteralPath $log -Encoding utf8
            $summary = ($output | Where-Object { $_ -match '^balance-|^compliant_failure=|^Probe error:' }) -join " "
            $rows += [pscustomobject]@{
                material=$material; damping_kg_s=$damping; dt_s=$rate.Dt; steps=$rate.Steps;
                sample_every=$rate.Stride; exit_code=$code; elapsed_s=([DateTime]::UtcNow-$started).TotalSeconds;
                recorded_head=$commit; dirty_source=$dirty; executable_sha256=$executableHash; started_utc=$started.ToString("o");
                command=($probe+" "+($arguments -join " ")); log=$log; trajectory=$trajectory; summary=$summary
            }
            $rows | Export-Csv -LiteralPath (Join-Path $destination "matrix.csv") -NoTypeInformation -Encoding utf8
            Write-Output "$name exit=$code $summary"
        }
    }
}
if ($rows.Where({$_.exit_code -ne 0}).Count -gt 0) { exit 2 }
