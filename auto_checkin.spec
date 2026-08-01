# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec cho auto-checkin-fb (onedir, multi-account hỗ trợ).

Đặc điểm:
  - Entry point = main.py (có nhánh --worker để multi-account spawn chính exe).
  - onedir: tạo thư mục dist/auto_checkin/ chứ 1 file exe + deps.
    Lý do dùng onedir thay vì onefile: multi-account spawn exe con với --worker;
    onefile mỗi lần spawn phải giải nén lại _MEIxxxx (chậm + lỗi khi 3 acc cùng
    spawn cùng lúc). onedir start gần như ngay.
  - Playwright cần bundle cả folder driver/ (node.exe + package) -> thêm datas.
  - Hidden imports: các module import động qua subprocess (worker_cli, ...).
"""
import os
import sys
import playwright

block_cipher = None

# --- Thư mục driver của Playwright (node.exe + package/cli.js) ---
pw_dir = os.path.dirname(playwright.__file__)
pw_driver = os.path.join(pw_dir, "driver")
playwright_datas = []
if os.path.isdir(pw_driver):
    playwright_datas.append((pw_driver, "playwright/driver"))

# --- Data file tĩnh (nếu có) ---
datas = []
datas += playwright_datas

# --- Hidden imports: các module import động + subpackage Playwright ---
hiddenimports = [
    "worker_cli",
    "multi_account",
    "pixel_painter",
    "dom_painter",
    "screen_painter",
    "browser",
    "config",
    "gui",
    "core",
    "fb_tasks",
    "msg_tasks",
    "pdf_pages",
    "screenshot",
    "region_picker",
    # Playwright internals (thường self-collected, thêm cho chắc)
    "playwright",
    "playwright.sync_api",
    "playwright._impl",
    "pywintypes",
]

a = Analysis(
    ["main.py"],
    pathex=[os.path.dirname(os.path.abspath("main.py"))],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Bỏ các lib lớn không dùng để giảm dung lượng
        "matplotlib",
        "numpy",
        "scipy",
        "pandas",
        "IPython",
        "notebook",
        "pytest",
        "tkinter.test",
        "unittest",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="auto_checkin",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,  # giữ console để worker subprocess in log ra stdout
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # để None nếu chưa có icon; đổi đường dẫn nếu có .ico
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="auto_checkin",
)
