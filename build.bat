@echo off
setlocal EnableDelayedExpansion
title Auto Pixel Painter - Build EXE
chcp 65001 >nul

echo ============================================================
echo    AUTO PIXEL PAINTER - DONG GOI UNG DUNG (.EXE)
echo ============================================================
echo.

REM --- Phat hien thu muc tool ---
set "TOOL_DIR=%~dp0"
set "TOOL_DIR=%TOOL_DIR:~0,-1%"
cd /d "%TOOL_DIR%"

REM --- 1. Kiem tra va cai PyInstaller ---
echo [1/3] Kiem tra PyInstaller...
python -m pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo   Chua co PyInstaller. Dang cai dat...
    python -m pip install pyinstaller
    if errorlevel 1 (
        echo [LOI] Khong the cai dat PyInstaller. Vui long kiem tra mang.
        pause
        exit /b 1
    )
)
echo   OK - Da co PyInstaller.
echo.

REM --- 2. Dong goi ung dung ---
echo [2/3] Dang dong goi ung dung bang PyInstaller...
echo.
python -m PyInstaller --clean --noconfirm --onedir --windowed --add-data "web_ui.html;." gui_web.py
if errorlevel 1 (
    echo.
    echo   [LOI] Co loi xay ra trong qua trinh dong goi!
    pause
    exit /b 1
)
echo.
echo   OK - Dong goi thanh cong!
echo.

REM --- 3. Sao chep cac file can thiet vao thu muc xuat ---
echo [3/3] Dang sao chep tai nguyen va tao file huong dan...
set "OUT_DIR=%TOOL_DIR%\dist\gui_web"

if exist "%TOOL_DIR%\config.example.yaml" (
    copy /y "%TOOL_DIR%\config.example.yaml" "%OUT_DIR%\config.example.yaml" >nul
    if not exist "%OUT_DIR%\config.yaml" (
        copy /y "%TOOL_DIR%\config.example.yaml" "%OUT_DIR%\config.yaml" >nul
    )
)

REM Tao file batch cai dat Chromium cho nguoi nhan
echo @echo off > "%OUT_DIR%\cai_dat_trinh_duyet.bat"
echo title Cai dat Chromium cho Playwright >> "%OUT_DIR%\cai_dat_trinh_duyet.bat"
echo echo Dang tai va cai dat Chromium (se co phan tram hien thi ben duoi)... >> "%OUT_DIR%\cai_dat_trinh_duyet.bat"
echo "%%~dp0_internal\playwright\driver\playwright.cmd" install chromium >> "%OUT_DIR%\cai_dat_trinh_duyet.bat"
echo echo. >> "%OUT_DIR%\cai_dat_trinh_duyet.bat"
echo echo Da cai dat xong trinh duyet! Bay gio ban co the chay gui_web.exe >> "%OUT_DIR%\cai_dat_trinh_duyet.bat"
echo pause >> "%OUT_DIR%\cai_dat_trinh_duyet.bat"

REM Tao file Huong dan su dung
echo HDSD: > "%OUT_DIR%\HUONG_DAN_SU_DUNG.txt"
echo ========================================== >> "%OUT_DIR%\HUONG_DAN_SU_DUNG.txt"
echo AUTO PIXEL PAINTER - HUONG DAN SU DUNG NHANH >> "%OUT_DIR%\HUONG_DAN_SU_DUNG.txt"
echo ========================================== >> "%OUT_DIR%\HUONG_DAN_SU_DUNG.txt"
echo. >> "%OUT_DIR%\HUONG_DAN_SU_DUNG.txt"
echo 1. Kich dup file "cai_dat_trinh_duyet.bat" o lan dau tien su dung >> "%OUT_DIR%\HUONG_DAN_SU_DUNG.txt"
echo    de tool tu dong tai va cai dat trinh duyet Chromium an. >> "%OUT_DIR%\HUONG_DAN_SU_DUNG.txt"
echo. >> "%OUT_DIR%\HUONG_DAN_SU_DUNG.txt"
echo 2. Kich dup file "gui_web.exe" de mo giao dien va su dung tool. >> "%OUT_DIR%\HUONG_DAN_SU_DUNG.txt"
echo. >> "%OUT_DIR%\HUONG_DAN_SU_DUNG.txt"
echo * Luu y: Giu nguyen cac file trong thu muc nay, chi can gui nguyen >> "%OUT_DIR%\HUONG_DAN_SU_DUNG.txt"
echo   thu muc "gui_web" (co the nen lai thanh file .zip) cho ban be dung. >> "%OUT_DIR%\HUONG_DAN_SU_DUNG.txt"

echo   OK - Da tao file cai_dat_trinh_duyet.bat va HUONG_DAN_SU_DUNG.txt
echo.

echo ============================================================
echo    HOAN THANH!
echo ============================================================
echo.
echo   Thu muc EXE cua ban tai: %OUT_DIR%
echo   Hay nen thu muc "gui_web" (trong %TOOL_DIR%\dist) thanh file ZIP
echo   roi gui file ZIP do cho ban be su dung!
echo.
pause
