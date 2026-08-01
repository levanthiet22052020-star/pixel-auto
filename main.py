"""Điểm vào của chương trình."""
from __future__ import annotations

import os
import sys

# Khi đóng gói exe, Playwright tính đường dẫn browser (.local-browsers) theo vị
# trí driver bundle trong _internal/ -> không thấy browser đã cài.
# Force dùng cache user mặc định (%USERPROFILE%\AppData\Local\ms-playwright).
# Phải đặt TRƯỚC khi import playwright.
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "0")


def main():
    # Chế độ worker (multi-account): exe gọi chính nó với --worker <config.json>.
    # worker_cli.py chứa logic tô 1 dải cột; nhánh này chỉ forward tham số.
    if "--worker" in sys.argv:
        import worker_cli
        # Bỏ 2 cờ đầu (--worker), phần còn lại là [config_file].
        # Đặt sys.argv về dạng worker_cli.main() mong đợi: [script, config_file].
        rest = [a for a in sys.argv if a != "--worker"]
        sys.argv = ["worker_cli"] + rest[1:]
        worker_cli.main()
        return

    # Mặc định mở giao diện đồ họa
    if "--setup" in sys.argv:
        # Chế độ dòng lệnh: thiết lập session (lưu cookie) lần đầu
        import config as cfgmod
        import browser as br
        cfg = cfgmod.load()
        br.setup_session(cfg.session_dir)
        return
    from gui import main as gui_main
    gui_main()


if __name__ == "__main__":
    main()
