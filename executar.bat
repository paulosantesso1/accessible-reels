@echo off
setlocal

if not exist "%~dp0.venv\Scripts\python.exe" (
    echo Ambiente virtual nao encontrado em .venv.
    echo Crie-o com: py -3.13 -m venv .venv
    exit /b 1
)

"%~dp0.venv\Scripts\python.exe" "%~dp0main.py" %*
exit /b %errorlevel%
