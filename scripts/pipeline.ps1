# Runs every step after the Track 1 benchmark, one at a time (benchmarks never overlap).
Set-Location (Split-Path $PSScriptRoot -Parent)
$log = "results\pipeline_log.txt"
function Step($name, [scriptblock]$cmd) {
    "[$(Get-Date -Format HH:mm:ss)] START $name" | Add-Content $log
    & $cmd *>> "results\pipeline_steps.txt"
    "[$(Get-Date -Format HH:mm:ss)] END   $name (exit $LASTEXITCODE)" | Add-Content $log
}
while (Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "*radar.benchmark*" }) { Start-Sleep 5 }
Step "radar.run_radar"       { .\run.bat -m radar.run_radar }
Step "radar.analysis"        { .\run.bat -m radar.analysis }
Step "flight.run_flight"     { .\run.bat -m flight.run_flight }
Remove-Item results\flight\benchmark_raw.csv -ErrorAction SilentlyContinue
Step "flight.benchmark"      { .\run.bat -m flight.benchmark --repeats 5 }
Step "flight.analysis"       { .\run.bat -m flight.analysis }
Step "corridor.run_corridor" { .\run.bat -m corridor.run_corridor }
Remove-Item results\corridor\benchmark_raw.csv -ErrorAction SilentlyContinue
Step "corridor.benchmark"    { .\run.bat -m corridor.benchmark --repeats 5 }
Step "corridor.analysis"     { .\run.bat -m corridor.analysis }
Step "qgis.build_project"    { .\run_qgis.bat qgis\build_project.py }
Step "qgis.render_bench"     { .\run_qgis.bat qgis\render_bench.py }
"[$(Get-Date -Format HH:mm:ss)] PIPELINE DONE" | Add-Content $log
