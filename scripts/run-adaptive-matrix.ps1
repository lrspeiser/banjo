param(
    [string]$BuildDirectory="build/win-integration",
    [ValidateSet('all','glass','oak','iron')][string]$Material='all',
    [double[]]$ErrorScales=@(1000,100,10),
    [string]$OutputDirectory="build/adaptive-matrix"
)
# Default retains all three materials. A material selector permits independent
# workers; the comparison requires the combined glass/oak/iron evidence.
$ErrorActionPreference='Stop'
$probe=(Resolve-Path -LiteralPath (Join-Path $BuildDirectory 'Release/banjo_solver_probe.exe')).Path
$binaryHash=(Get-FileHash -LiteralPath $probe -Algorithm SHA256).Hash.ToLowerInvariant()
$head=(& git rev-parse HEAD).Trim()
$dirty=[bool](& git status --porcelain)
$culture=[Globalization.CultureInfo]::InvariantCulture
$materials=if ($Material -eq 'all') { @('glass','oak','iron') } else { @($Material) }
$cases=@(@{Name='fixed'; Mode='compliant'; Dt='0.00000078125'; Steps='6400'; Stride='128'; Scale='0'})
foreach ($scale in $ErrorScales) {
    if ([double]::IsNaN($scale) -or [double]::IsInfinity($scale) -or $scale -le 0) { throw 'Invalid error scale' }
    $value=$scale.ToString('R',$culture)
    $cases+=@{Name="adaptive-$value"; Mode='adaptive'; Dt='0.0001'; Steps='50'; Stride='1'; Scale=$value}
}
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$destination=(Resolve-Path -LiteralPath $OutputDirectory).Path
$rows=@()
foreach ($substance in $materials) {
    foreach ($case in $cases) {
        $name="$substance-$($case.Name)"
        $trajectory=Join-Path $destination ($name+'-trajectory.csv')
        $log=Join-Path $destination ($name+'.txt')
        $arguments=@('--material',$substance,'--case','floor','--step-mode',$case.Mode,
            '--voxel-size','0.04','--gap','0.001','--speed','1','--gravity','0',
            '--normal-stiffness','100000000','--normal-damping','10000','--max-compression','0.005',
            '--dt',$case.Dt,'--steps',$case.Steps,'--trajectory',$trajectory,'--sample-every',$case.Stride)
        if ($case.Mode -eq 'adaptive') { $arguments+=@('--error-scale',$case.Scale,'--min-trial-dt','0.00000000001') }
        $started=[DateTime]::UtcNow
        $output=& $probe @arguments 2>&1
        $code=$LASTEXITCODE
        $output | Set-Content -LiteralPath $log -Encoding utf8
        $summary=($output | Where-Object { $_ -match '^balance-|^adaptive_failure=|^compliant_failure=|^Probe error:' }) -join ' '
        $rows+=[pscustomobject]@{
            material=$substance; damping_kg_s='10000'; experiment=$case.Name; integrator=$case.Mode; error_scale=$case.Scale;
            dt_s=$case.Dt; steps=$case.Steps; sample_every=$case.Stride; exit_code=$code;
            elapsed_s=([DateTime]::UtcNow-$started).TotalSeconds; recorded_head=$head; dirty_source=$dirty;
            executable_sha256=$binaryHash; started_utc=$started.ToString('o');
            command=($probe+' '+($arguments -join ' ')); log=$log; trajectory=$trajectory; summary=$summary
        }
        $rows | Export-Csv -LiteralPath (Join-Path $destination 'matrix.csv') -NoTypeInformation -Encoding utf8
        Write-Output "$name exit=$code $summary"
    }
}
if ($rows.Where({$_.exit_code -ne 0}).Count -gt 0) { exit 2 }
