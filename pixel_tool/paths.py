"""Quản lý đường dẫn dữ liệu — KHÔNG bị mất khi chạy bằng file exe (PyInstaller).

Quan trọng: khi build bằng PyInstaller, `__file__` trỏ vào thư mục tạm _MEIxxxx
bị xóa khi thoát. Do đó ta phải lưu config / tiến độ / session vào thư mục cố định
NGOÀI thư mục tạm:
  - Khi chạy bằng .exe: thư mục chứa file .exe (sys.executable).
  - Khi chạy bằng python: thư mục chứa script (__file__).

Nhờ vậy: đóng app → mở lại → config + tiến độ tô màu vẫn còn → resume được,
không phải vẽ lại từ đầu.
"""
from __future__ import annotations

import os
import sys


def app_dir() -> str:
    """Thư mục gốc để lưu dữ liệu (config, tiến độ, session, screenshots).

    - frozen (exe): thư mục chứa file exe (ổn định, không bị xóa).
    - dev (python): thư mục chứa script.
    """
    if getattr(sys, "frozen", False):
        # Chạy bằng exe PyInstaller → dùng thư mục chứa exe.
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))
