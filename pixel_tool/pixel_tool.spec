# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec cho Pixel Painter.

Build:  pyinstaller pixel_tool.spec
Kết quả: dist/PixelPainter/PixelPainter.exe

Chế độ onedir (ổn định với Playwright + Tkinter).
Tool dùng Chrome thật đã cài (channel="chrome") nên không cần bundle Chromium.
"""
import sys
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas = []
binaries = []
hiddenimports = []

# Playwright cần node.exe + package/ → collect_all lấy hết.
for d, b, h in (collect_all("playwright"),):
    datas += d
    binaries += b
    hiddenimports += h

# Pillow / PIL
for d, b, h in (collect_all("PIL"),):
    datas += d
    binaries += b
    hiddenimports += h

# mss (chụp màn hình)
for d, b, h in (collect_all("mss"),):
    datas += d
    binaries += b
    hiddenimports += h

# yaml
hiddenimports += collect_submodules("yaml")

# Thư mục driver playwright (node.exe + package cli.js) — collect_all đã lo,
# nhưng đảm bảo thêm以防 thiếu.
from PyInstaller.utils.hooks import get_package_paths
try:
    pw_paths = get_package_paths("playwright")
    import os
    pw_driver = os.path.join(os.path.dirname(pw_paths.pkgloc), "driver")
except Exception:
    pw_driver = None


a = Analysis(
    ["main_pixel.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["PyMuPDF", "fitz", "apscheduler"],  # pixel tool không dùng
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PixelPainter",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # GUI app, không hiện console
    disable_windowed_traceback=False,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="PixelPainter",
)
