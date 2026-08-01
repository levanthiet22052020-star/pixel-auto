@echo off
setlocal EnableDelayedExpansion
title Auto Pixel Painter - Setup

echo ============================================================
echo    AUTO PIXEL PAINTER - CAI DAT MOI TRUONG
echo ============================================================
echo.

REM --- Phat hien thu muc tool (canh file .bat nay) ---
set "TOOL_DIR=%~dp0"
set "TOOL_DIR=%TOOL_DIR:~0,-1%"
echo Thu muc tool: %TOOL_DIR%
echo.

REM --- 1. Kiem tra Python ---
echo [1/4] Kiem tra Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo   [LOI] Khong tim thay Python!
    echo.
    echo   Tai Python 3.10+ tu: https://www.python.org/downloads/
    echo   Khi cai dat, TICK vao "Add Python to PATH"
    echo.
    pause
    exit /b 1
)
for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set "PY_VER=%%v"
echo   OK - Python %PY_VER%
echo.

REM --- 2. Cai dependencies ---
echo [2/4] Cai thu vien tu requirements.txt...
cd /d "%TOOL_DIR%"
python -m pip install --upgrade pip >nul 2>&1
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo   [LOI] Loi cai thu vien. Kiem tra mang roi chay lai.
    pause
    exit /b 1
)
echo   OK - Da cai xong thu vien
echo.

REM --- 3. Cai Playwright Chromium ---
echo [3/4] Cai trinh duyet Chromium cho Playwright...
python -m playwright install chromium
if errorlevel 1 (
    echo   [LOI] Loi cai Chromium. Kiem tra mang roi chay lai.
    pause
    exit /b 1
)
echo   OK - Da cai Chromium
echo.

REM --- 4. Tao run.bat, run.vbs, shortcut Desktop ---
echo [4/4] Tao run.bat + run.vbs + shortcut Desktop...

REM run.bat (chay tool co log console, de debug)
> "%TOOL_DIR%\run.bat" echo @echo off
>> "%TOOL_DIR%\run.bat" echo chcp 65001 ^>nul
>> "%TOOL_DIR%\run.bat" echo cd /d "%%~dp0"
>> "%TOOL_DIR%\run.bat" echo title Auto Pixel Painter
>> "%TOOL_DIR%\run.bat" echo python gui_web.py
>> "%TOOL_DIR%\run.bat" echo echo.
>> "%TOOL_DIR%\run.bat" echo echo Tool da thoat. Nhan phim bat ky de dong.
>> "%TOOL_DIR%\run.bat" echo pause ^>nul

REM run.vbs (chay tool an console, chi hien Web UI)
> "%TOOL_DIR%\run.vbs" echo Set objShell = CreateObject("WScript.Shell")
>> "%TOOL_DIR%\run.vbs" echo objShell.CurrentDirectory = "%TOOL_DIR%"
>> "%TOOL_DIR%\run.vbs" echo objShell.Run "pythonw gui_web.py", 0, False

REM Shortcut desktop tro run.vbs
set "DESKTOP=%USERPROFILE%\Desktop"
set "SHORTCUT=%DESKTOP%\Auto Pixel Painter.lnk"
> "%TEMP%\_mksc.vbs" echo Set ws = CreateObject("WScript.Shell")
>> "%TEMP%\_mksc.vbs" echo Set sc = ws.CreateShortcut("%SHORTCUT%")
>> "%TEMP%\_mksc.vbs" echo sc.TargetPath = "%TOOL_DIR%\run.vbs"
>> "%TEMP%\_mksc.vbs" echo sc.WorkingDirectory = "%TOOL_DIR%"
>> "%TEMP%\_mksc.vbs" echo sc.IconLocation = "shell32.dll,13"
>> "%TEMP%\_mksc.vbs" echo sc.Description = "Auto Pixel Painter"
>> "%TEMP%\_mksc.vbs" echo sc.Save
cscript //nologo "%TEMP%\_mksc.vbs" >nul 2>&1
del "%TEMP%\_mksc.vbs" >nul 2>&1

if exist "%SHORTCUT%" (
    echo   OK - Shortcut: %SHORTCUT%
) else (
    echo   Canh bao: Khong tao duoc shortcut. Dung run.bat hoac run.vbs trong thu muc tool.
)
echo.

REM --- Hoan tat ---
echo ============================================================
echo    CAI DAT HOAN TAT!
echo ============================================================
echo.
echo   Thu muc tool: %TOOL_DIR%
echo.
echo   Cach chay:
echo     - Bam dup shortcut "Auto Pixel Painter" tren Desktop
echo     - Hoac chay: run.bat  (co log console)
echo     - Hoac chay: run.vbs  (an console, chi hien Web UI)
echo     - Hoac lenh:  python gui_web.py
echo.
echo   Khi mo Web UI: nhap anh + tai khoan DATN ngay trong giao diện.
echo.
pause
