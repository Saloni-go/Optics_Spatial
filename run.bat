@echo off
rem Runs a Python script with QGIS's Python (has GDAL, numpy, scipy, matplotlib, psutil).
call "C:\Program Files\QGIS 3.44.12\bin\o4w_env.bat" >nul 2>&1
set PYTHONPATH=%~dp0;%PYTHONPATH%
set PYTHONIOENCODING=utf-8
python %*
