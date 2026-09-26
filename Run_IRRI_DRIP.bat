@echo off
title IRRI-DRIP - Drip Irrigation Network Design
cd /d "%~dp0"
set "LOG=%~dp0install_log.txt"
set "VENVDIR=%~dp0.venv"
set "VENVPY=%VENVDIR%\Scripts\python.exe"

echo ===== IRRI-DRIP run log ===== > "%LOG%"
echo %DATE% %TIME% >> "%LOG%"

echo ================================================
echo   IRRI DRIP v3.0.0
echo   Drip Irrigation Network Design
echo   Water Management Research Institute
echo ================================================
echo.

echo [1/3] Looking for a supported Python (3.12 or 3.11)...
set "PY="
py -3.12 -c "import sys" >nul 2>&1
if not errorlevel 1 set "PY=py -3.12"
if defined PY goto haspy
py -3.11 -c "import sys" >nul 2>&1
if not errorlevel 1 set "PY=py -3.11"
if defined PY goto haspy
goto nopython

:haspy
echo       OK - using: %PY%
%PY% --version
%PY% -c "import sys; print(sys.version)" >> "%LOG%" 2>&1
echo.

echo [2/3] Preparing the isolated Python environment...
if exist "%~dp0.deps_ok" goto depsok
if not exist "%VENVDIR%" goto makeenv
echo       Removing the previous incomplete environment...
rmdir /s /q "%VENVDIR%"

:makeenv
%PY% -m venv "%VENVDIR%" >> "%LOG%" 2>&1
if not exist "%VENVPY%" goto venvfail
echo       Installing libraries. First run only, 2 to 5 minutes.
"%VENVPY%" -m pip install --no-compile --disable-pip-version-check -r "%~dp0requirements.txt" >> "%LOG%" 2>&1
if errorlevel 1 goto pipfail
"%VENVPY%" -c "import streamlit, pandas, numpy, openpyxl, plotly, folium, streamlit_folium" >> "%LOG%" 2>&1
if errorlevel 1 goto pipfail
echo ok> "%~dp0.deps_ok"
echo       OK - libraries installed and verified.
goto run

:depsok
rem The marker alone is not proof: a new version may need libraries the
rem existing environment does not have. v0.7.0 added folium and
rem streamlit-folium for the map, and a marker written by v0.6.0 would
rem have skipped straight past installing them. v2.0.0 adds plotly for
rem the OpenIrri-style charts; the same check catches it.
"%VENVPY%" -c "import streamlit, pandas, numpy, openpyxl, plotly, folium, streamlit_folium" >nul 2>&1
if errorlevel 1 goto refresh
echo       OK - environment already prepared.
goto run

:refresh
echo       New libraries are required by this version. Installing...
"%VENVPY%" -m pip install --no-compile --disable-pip-version-check -r "%~dp0requirements.txt" >> "%LOG%" 2>&1
if errorlevel 1 goto pipfail
"%VENVPY%" -c "import streamlit, pandas, numpy, openpyxl, plotly, folium, streamlit_folium" >> "%LOG%" 2>&1
if errorlevel 1 goto pipfail
echo       OK - environment updated.

:run
echo.
echo [3/3] Starting IRRI-DRIP...
echo.
echo   Your browser will open by itself at http://localhost:8501
echo   (or 8502, 8503... if another program such as OpenIrri or
echo   IRRI-DRIP v1 is already using 8501 - the address is shown below).
echo   KEEP THIS WINDOW OPEN while you work.
echo   To stop the program, press Ctrl+C here.
echo.
"%VENVPY%" -m streamlit run "%~dp0app.py" --browser.gatherUsageStats=false
echo.
echo IRRI-DRIP has stopped.
pause
exit /b 0

:nopython
echo.
echo   [ERROR] No supported Python version was found.
echo.
echo   IRRI-DRIP needs Python 3.12 or 3.11.
echo   Python 3.13 and 3.14 are NOT supported: the scientific
echo   libraries have no ready made packages for them yet.
echo.
echo   Install Python 3.12 from:
echo     https://www.python.org/downloads/release/python-31210/
echo   Choose "Windows installer (64-bit)" and tick
echo   "Add python.exe to PATH" during installation.
echo.
pause
exit /b 1

:venvfail
echo.
echo   [ERROR] Could not create the Python environment.
echo   See install_log.txt
echo.
pause
exit /b 1

:pipfail
echo.
echo   [ERROR] Library installation failed.
echo   See install_log.txt
echo.
pause
exit /b 1
