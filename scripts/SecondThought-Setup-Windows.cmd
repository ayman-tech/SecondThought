@echo off
rem Double-click setup for Windows. It runs install.ps1 from GitHub, the same
rem as pasting the PowerShell command from the website.
title SecondThought setup
echo Setting up SecondThought. The first time takes about 5 minutes.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/ayman-tech/SecondThought/master/scripts/install.ps1 | iex"
echo.
pause
