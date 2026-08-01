"""Điểm vào của tool Auto Check-in Facebook + Messenger."""
from __future__ import annotations

import sys


def main():
    if "--setup" in sys.argv:
        # Chế độ dòng lệnh: đăng nhập Facebook lần đầu
        import config as cfgmod
        import browser as br
        cfg = cfgmod.load()
        br.setup_session(cfg.session_dir)
        return
    from gui_fb import main as gui_main
    gui_main()


if __name__ == "__main__":
    main()
