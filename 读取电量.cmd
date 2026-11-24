@echo off
chcp 65001 >nul
cd /d "%~dp0"
python eweadn_battery.py --once
echo.
pause
