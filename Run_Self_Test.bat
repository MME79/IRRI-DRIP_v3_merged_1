@echo off
title IRRI-DRIP - Self-test
cd /d "%~dp0"
set "VENVPY=%~dp0.venv\Scripts\python.exe"
set "LOG=%~dp0test_log.txt"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

echo ================================================
echo   IRRI DRIP v3.0.0 - Self-test on this computer
echo ================================================
echo.
if not exist "%VENVPY%" goto novenv

echo ===== IRRI-DRIP self-test ===== > "%LOG%"
echo %DATE% %TIME% >> "%LOG%"
"%VENVPY%" -c "import sys, platform; print(sys.version); print(platform.platform())" >> "%LOG%" 2>&1
"%VENVPY%" -c "import streamlit, pandas, numpy, plotly, folium, openpyxl; print('streamlit', streamlit.__version__, '| pandas', pandas.__version__, '| numpy', numpy.__version__, '| plotly', plotly.__version__)" >> "%LOG%" 2>&1

echo [1/3] Installing the test runner (pytest)...
"%VENVPY%" -m pip install pytest >> "%LOG%" 2>&1

echo [2/3] Running the automated tests (about one minute)...
echo ===== PYTEST ===== >> "%LOG%"
"%VENVPY%" -m pytest tests -q -p no:cacheprovider >> "%LOG%" 2>&1
echo PYTEST EXIT CODE %ERRORLEVEL% >> "%LOG%"

echo [3/3] Running the independent validation scripts...
echo ===== worked_example ===== >> "%LOG%"
"%VENVPY%" validation\worked_example.py >> "%LOG%" 2>&1
echo worked_example EXIT CODE %ERRORLEVEL% >> "%LOG%"
echo ===== edge_cases ===== >> "%LOG%"
"%VENVPY%" validation\edge_cases.py >> "%LOG%" 2>&1
echo edge_cases EXIT CODE %ERRORLEVEL% >> "%LOG%"
echo ===== step_method ===== >> "%LOG%"
"%VENVPY%" validation\step_method.py >> "%LOG%" 2>&1
echo step_method EXIT CODE %ERRORLEVEL% >> "%LOG%"
echo ===== published_cases ===== >> "%LOG%"
"%VENVPY%" validation\published_cases.py >> "%LOG%" 2>&1
echo published_cases EXIT CODE %ERRORLEVEL% >> "%LOG%"
echo SELF-TEST FINISHED %DATE% %TIME% >> "%LOG%"

echo.
echo   Finished. The full results are in test_log.txt
echo.
timeout /t 20
exit /b 0

:novenv
echo   The program environment does not exist yet.
echo   Run Run_IRRI_DRIP.bat once first, then run this file again.
echo NO ENVIRONMENT - run Run_IRRI_DRIP.bat first > "%LOG%"
pause
exit /b 1
