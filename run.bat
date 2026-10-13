@echo off
rem Runs a Python script with QGIS's Python (has GDAL, numpy, scipy, matplotlib, psutil).
rem Finds the newest QGIS install under Program Files (or OSGeo4W); set QGIS_ROOT to override.
setlocal enabledelayedexpansion
if defined QGIS_ROOT if exist "%QGIS_ROOT%\bin\o4w_env.bat" set "O4W=%QGIS_ROOT%\bin\o4w_env.bat"
if not defined O4W (
  for /f "delims=" %%d in ('dir /b /ad /o-n "C:\Program Files\QGIS*" 2^>nul') do (
    if not defined O4W if exist "C:\Program Files\%%d\bin\o4w_env.bat" set "O4W=C:\Program Files\%%d\bin\o4w_env.bat"
  )
)
if not defined O4W if exist "C:\OSGeo4W\bin\o4w_env.bat" set "O4W=C:\OSGeo4W\bin\o4w_env.bat"
if not defined O4W (
  echo QGIS not found. Install QGIS 3.x from qgis.org, or set QGIS_ROOT to its folder.
  exit /b 1
)
endlocal & call "%O4W%" >nul 2>&1
set PYTHONPATH=%~dp0;%PYTHONPATH%
set PYTHONIOENCODING=utf-8
python %*
