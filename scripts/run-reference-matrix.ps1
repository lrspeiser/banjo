param(
    [string]$BuildDirectory = "build/win-integration",
    [ValidateRange(0.001, 0.25)][double]$VoxelSize = 0.12,
    [string]$OutputDirectory = "build/reference-matrix"
)
# Run from the repository root. Always retain all three reference substances.
# These are numerical elastic approximations, not material calibration results.
$ErrorActionPreference = "Stop"
$probe = (Resolve-Path -LiteralPath (Join-Path $BuildDirectory "Release/banjo_solver_probe.exe")).Path
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$destination = (Resolve-Path -LiteralPath $OutputDirectory).Path
$culture = [Globalization.CultureInfo]::InvariantCulture
$cases = @(
    @{Name="free"; Geometry="free"; Mode="raw"; Dt="0.002"; Steps="1"; Restitution="1"},
    @{Name="raw-floor"; Geometry="floor"; Mode="raw"; Dt="0.002"; Steps="1"; Restitution="1"},
    @{Name="event-floor"; Geometry="floor"; Mode="events"; Dt="0.002"; Steps="1"; Restitution="1"},
    @{Name="event-half-step"; Geometry="floor"; Mode="events"; Dt="0.001"; Steps="2"; Restitution="1"},
    @{Name="event-quarter-step"; Geometry="floor"; Mode="events"; Dt="0.0005"; Steps="4"; Restitution="1"},
    @{Name="event-loss"; Geometry="floor"; Mode="events"; Dt="0.002"; Steps="1"; Restitution="0.3"}
)
$rows = @()
$commit = (& git rev-parse HEAD).Trim()
$dirty = [bool](& git status --porcelain)
foreach ($material in @("glass", "oak", "iron")) {
    foreach ($case in $cases) {
        $arguments = @("--material", $material, "--case", $case.Geometry,
            "--step-mode", $case.Mode, "--voxel-size", $VoxelSize.ToString("R", $culture),
            "--dt", $case.Dt, "--steps", $case.Steps, "--gap", "0.001", "--speed", "1")
        if ($case.Mode -eq "events") { $arguments += @("--restitution", $case.Restitution) }
        $log = Join-Path $destination ($material + "-" + $case.Name + ".txt")
        $started = [DateTime]::UtcNow
        $output = & $probe @arguments 2>&1
        $code = $LASTEXITCODE
        $output | Set-Content -LiteralPath $log -Encoding utf8
        $summary = ($output | Where-Object { $_ -match '^balance-|^advance_failure=|^Probe error:' }) -join " "
        $rows += [pscustomobject]@{
            material=$material; experiment=$case.Name; voxel_size_m=$VoxelSize;
            dt_s=$case.Dt; steps=$case.Steps; restitution=$case.Restitution;
            exit_code=$code; elapsed_s=([DateTime]::UtcNow-$started).TotalSeconds;
            commit=$commit; dirty_source=$dirty; started_utc=$started.ToString("o");
            command=($probe + " " + ($arguments -join " ")); log=$log; summary=$summary
        }
        # Preserve completed rows even if the next case is interrupted.
        $rows | Export-Csv -LiteralPath (Join-Path $destination "matrix.csv") -NoTypeInformation -Encoding utf8
        Write-Output "$material $($case.Name): exit=$code $summary"
    }
}
if ($rows.Where({$_.exit_code -ne 0}).Count -gt 0) { exit 2 }
