param(
    [string]$BuildDirectory = "build/win-integration",
    [ValidateRange(0.001, 0.25)][double]$VoxelSize = 0.04,
    [switch]$FineOnly,
    [string]$OutputDirectory = "build/compliance-matrix"
)
# An explicitly selected interface law; not a replacement for constant restitution.
# Per-contact stiffness is not yet a resolution-independent surface compilation.
$ErrorActionPreference = "Stop"
$probe = (Resolve-Path -LiteralPath (Join-Path $BuildDirectory "Release/banjo_solver_probe.exe")).Path
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$destination = (Resolve-Path -LiteralPath $OutputDirectory).Path
$culture = [Globalization.CultureInfo]::InvariantCulture
$cases = @(
    @{Name="elastic-50us"; Dt="0.00005"; Steps="100"; Damping="0"; Gravity="0"; Gap="0.001"; Speed="1"},
    @{Name="elastic-25us"; Dt="0.000025"; Steps="200"; Damping="0"; Gravity="0"; Gap="0.001"; Speed="1"},
    @{Name="elastic-12.5us"; Dt="0.0000125"; Steps="400"; Damping="0"; Gravity="0"; Gap="0.001"; Speed="1"},
    @{Name="damped-50us"; Dt="0.00005"; Steps="100"; Damping="10000"; Gravity="0"; Gap="0.001"; Speed="1"},
    @{Name="damped-25us"; Dt="0.000025"; Steps="200"; Damping="10000"; Gravity="0"; Gap="0.001"; Speed="1"},
    @{Name="damped-12.5us"; Dt="0.0000125"; Steps="400"; Damping="10000"; Gravity="0"; Gap="0.001"; Speed="1"},
    @{Name="loaded-50us"; Dt="0.00005"; Steps="400"; Damping="10000"; Gravity="9.81"; Gap="0"; Speed="0"},
    @{Name="loaded-25us"; Dt="0.000025"; Steps="800"; Damping="10000"; Gravity="9.81"; Gap="0"; Speed="0"},
    @{Name="loaded-12.5us"; Dt="0.0000125"; Steps="1600"; Damping="10000"; Gravity="9.81"; Gap="0"; Speed="0"}
)
if ($FineOnly) { $cases = $cases | Where-Object { $_.Dt -eq "0.0000125" } }
$rows = @()
$commit = (& git rev-parse HEAD).Trim()
$dirty = [bool](& git status --porcelain)
foreach ($material in @("glass", "oak", "iron")) {
    foreach ($case in $cases) {
        $arguments = @("--material",$material,"--case","floor","--step-mode","compliant",
            "--voxel-size",$VoxelSize.ToString("R",$culture),"--dt",$case.Dt,"--steps",$case.Steps,
            "--gap",$case.Gap,"--speed",$case.Speed,"--gravity",$case.Gravity,
            "--normal-stiffness","100000000","--normal-damping",$case.Damping,"--max-compression","0.005")
        $log = Join-Path $destination ($material+"-"+$case.Name+".txt")
        $started = [DateTime]::UtcNow
        $output = & $probe @arguments 2>&1
        $code = $LASTEXITCODE
        $output | Set-Content -LiteralPath $log -Encoding utf8
        $summary = ($output | Where-Object { $_ -match '^balance-|^compliant_failure=|^Probe error:' }) -join " "
        $rows += [pscustomobject]@{
            material=$material; experiment=$case.Name; voxel_size_m=$VoxelSize;
            dt_s=$case.Dt; steps=$case.Steps; stiffness_n_m=100000000; damping_kg_s=$case.Damping;
            maximum_compression_m=.005; gravity_m_s2=$case.Gravity; gap_m=$case.Gap; speed_m_s=$case.Speed;
            exit_code=$code; elapsed_s=([DateTime]::UtcNow-$started).TotalSeconds;
            commit=$commit; dirty_source=$dirty; started_utc=$started.ToString("o");
            command=($probe+" "+($arguments -join " ")); log=$log; summary=$summary
        }
        $rows | Export-Csv -LiteralPath (Join-Path $destination "matrix.csv") -NoTypeInformation -Encoding utf8
        Write-Output "$material $($case.Name): exit=$code $summary"
    }
}
if ($rows.Where({$_.exit_code -ne 0}).Count -gt 0) { exit 2 }
