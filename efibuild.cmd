@echo off
REM Lanceur efibuild pour Windows. Necessite Python 3.9 ou plus recent.
setlocal
cd /d "%~dp0"
where py >nul 2>nul && (py -3 -m efibuilder %* & exit /b %errorlevel%)
python -m efibuilder %*
