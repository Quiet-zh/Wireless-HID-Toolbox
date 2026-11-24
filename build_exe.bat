@echo off
setlocal
cd /d "%~dp0"

set "MODE=onefile"

rem 支持 build_exe.bat onefile / onedir / 1 / 2
if not "%~1"=="" (
  if "%~1"=="1" (
    set "MODE=onefile"
  ) else if "%~1"=="2" (
    set "MODE=onedir"
  ) else (
    set "MODE=%~1"
  )
  goto :mode_ready
)

echo.
echo 选择打包模式：
echo   [1] onefile 单文件（默认，分发方便）
echo   [2] onedir 文件夹（启动更快，不需要解压）
echo.
set /p "CHOICE=请输入 1 或 2 [1]: "
if "%CHOICE%"=="2" set "MODE=onedir"
if /i "%CHOICE%"=="onedir" set "MODE=onedir"

:mode_ready
if /i "%MODE%"=="onefile" goto :mode_ok
if /i "%MODE%"=="onedir" goto :mode_ok
echo [ERROR] 未知打包模式: %MODE%
echo         只支持 onefile 或 onedir
pause
exit /b 1

:mode_ok
python -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
  echo [ERROR] 未安装 PyInstaller。
  echo         请先运行: python -m pip install -r requirements-build.txt
  pause
  exit /b 1
)

echo.
echo 当前模式: %MODE%
python -m PyInstaller --noconfirm --clean --%MODE% --noconsole --optimize 2 ^
  --name WirelessHIDToolbox ^
  --icon app.ico ^
  --version-file version_info.txt ^
  --distpath dist --workpath build ^
  --exclude-module unittest ^
  --exclude-module doctest ^
  --exclude-module pydoc ^
  --exclude-module pdb ^
  --exclude-module test ^
  --hidden-import battery_panel ^
  --hidden-import tray_app ^
  --hidden-import mouse_test_gui ^
  --hidden-import mouse_events ^
  --hidden-import keyboard_view ^
  --hidden-import window_behavior ^
  --hidden-import theme ^
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
  --hidden-import version ^
  main.py

if errorlevel 1 (
  echo [ERROR] 打包失败。
  pause
  exit /b 1
)

echo.
if /i "%MODE%"=="onefile" (
  echo 打包完成: dist\WirelessHIDToolbox.exe
  echo 单文件模式：首次启动会先解压，稍慢；分发只需这一个 exe。
) else (
  echo 打包完成: dist\WirelessHIDToolbox\WirelessHIDToolbox.exe
  echo 文件夹模式：启动更快；分发时请整个 dist\WirelessHIDToolbox 一起打包。
)
echo 双击 exe 会直接打开主显示界面。
pause
