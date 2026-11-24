@echo off
setlocal
cd /d "%~dp0"

python -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
  echo [ERROR] 未安装 PyInstaller。
  echo         请先运行: python -m pip install -r requirements-build.txt
  pause
  exit /b 1
)

python -m PyInstaller --noconfirm --clean --onefile --noconsole ^
  --name WirelessHIDToolbox ^
  --hidden-import battery_panel ^
  --hidden-import tray_app ^
  --hidden-import mouse_test_gui ^
  --hidden-import mouse_events ^
  --hidden-import keyboard_view ^
  --hidden-import app ^
  --hidden-import device_registry ^
  --hidden-import generic_protocols ^
  --hidden-import generic_scan ^
  --hidden-import tray_common ^
  --hidden-import last_state ^
  --hidden-import device_lock ^
  --hidden-import eweadn_proto ^
  --hidden-import pmo_proto ^
  --hidden-import hid_win ^
  --hidden-import win_icon ^
  --hidden-import win_link ^
  --hidden-import win_shell ^
  main.py

if errorlevel 1 (
  echo [ERROR] 打包失败。
  pause
  exit /b 1
)

echo.
echo 打包完成: dist\WirelessHIDToolbox.exe
echo 双击 exe 会直接打开主显示界面。
pause
