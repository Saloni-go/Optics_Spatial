# Re-runs the experiments affected by the three fixes (threads, gain-based adaptive sampling,
# landmark A*), one at a time.  Old rows of the re-run experiments are removed first.
Set-Location (Split-Path $PSScriptRoot -Parent)
$log = "results\pipeline_fixes_log.txt"
function Step($name, [scriptblock]$cmd) {
    "[$(Get-Date -Format HH:mm:ss)] START $name" | Out-File $log -Append -Encoding utf8
    & $cmd 2>&1 | Out-File "results\pipeline_fixes_steps.txt" -Append -Encoding utf8
    "[$(Get-Date -Format HH:mm:ss)] END   $name (exit $LASTEXITCODE)" | Out-File $log -Append -Encoding utf8
}
python scripts\drop_rows.py results\radar\benchmark_raw.csv E4_radars
python scripts\drop_rows.py results\flight\benchmark_raw.csv F6_optimise
python scripts\drop_rows.py results\corridor\benchmark_raw.csv C2_alpha C6_multi_query
Step "radar.benchmark E4"      { .\run.bat -m radar.benchmark E4 --repeats 3 }
Step "radar.analysis"          { .\run.bat -m radar.analysis }
Step "flight.benchmark F6"     { .\run.bat -m flight.benchmark F6 --repeats 5 }
Step "flight.spacing_study"    { .\run.bat -m flight.spacing_study }
Step "flight.analysis"         { .\run.bat -m flight.analysis }
Step "corridor.run_corridor"   { .\run.bat -m corridor.run_corridor }
Step "corridor.benchmark C2 C6" { .\run.bat -m corridor.benchmark C2 C6 --repeats 3 }
Step "corridor.analysis"       { .\run.bat -m corridor.analysis }
"[$(Get-Date -Format HH:mm:ss)] PIPELINE DONE" | Out-File $log -Append -Encoding utf8
