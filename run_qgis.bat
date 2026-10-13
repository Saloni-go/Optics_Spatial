@echo off
rem Runs a script with QGIS's Python plus the QGIS libraries (PyQGIS), for project building / render benchmarks.
set PYTHONPATH=%~dp0;%PYTHONPATH%
set PYTHONIOENCODING=utf-8
call "C:\Program Files\QGIS 3.44.12\bin\python-qgis-ltr.bat" %*
