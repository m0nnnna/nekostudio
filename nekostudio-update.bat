@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0nekostudio-update.ps1" %*
exit /b %ERRORLEVEL%
