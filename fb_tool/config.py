"""Quản lý cấu hình: lưu/đọc config.yaml."""
from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional

import yaml

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")


@dataclass
class Config:
    # --- Facebook ---
    page_url: str = ""                       # link trang FB cần comment
    comment_template: str = "{hh}:{mm} N{d}.{m}.{yy} LVT"
    like_after_comment: bool = True

    # --- Messenger ---
    contact_name: str = ""                   # tên người nhận hoặc link chat
    send_pdf: bool = True                    # có gửi ảnh PDF qua Messenger không

    # --- PDF ---
    pdf_path: str = ""                       # đường dẫn file PDF
    start_page: int = 1                      # trang bắt đầu

    # --- Lịch ---
    start_time: str = "08:30"                # HH:MM
    end_time: str = "17:30"                  # HH:MM
    fb_interval_minutes: int = 60            # mỗi bao nhiêu phút comment FB
    msg_interval_minutes: int = 60           # mỗi bao nhiêu phút gửi Messenger
    msg_offset_minutes: int = 15             # lệch sau FB để không đụng

    # --- Đường dẫn ---
    screenshot_root: str = ""                # thư mục gốc chứa ảnh chụp
    session_dir: str = ""                    # thư mục chứa phiên đăng nhập

    # --- Chụp & cắt ---
    crop_messenger_left: bool = True         # cắt thanh bạn bè bên trái Messenger

    # --- Pixel Painter ---
    pixel_url: str = ""                      # URL trang pixel canvas
    pixel_site_url: str = ""                 # URL trang chính (để đăng nhập), vd https://datn.unifolio.io
    pixel_username: str = ""                 # tài khoản đăng nhập trang pixel
    pixel_password: str = ""                 # mật khẩu đăng nhập trang pixel
    pixel_wait_for_login: bool = False       # True = đăng nhập xong chờ người dùng bấm OK
    pixel_grid_w: int = 384                  # số ô ngang (canvas thật của trang)
    pixel_grid_h: int = 240                  # số ô dọc (canvas thật của trang)
    pixel_rate_limit: int = 120              # số ô tối đa mỗi kỳ (trang giới hạn 120 ô/5 phút)
    pixel_rate_window: int = 300             # độ dài kỳ giới hạn (giây)
    pixel_cooldown_seconds: float = 0.5      # giây chờ giữa mỗi ô
    pixel_jitter_seconds: float = 0.2        # nhiễu ± giây cho cooldown
    pixel_palette_path: str = ""             # file palette (#RRGGBB/dòng), rỗng = tự dò/web-safe
    pixel_dither: bool = False               # Floyd-Steinberg dithering
    pixel_bg_skip: bool = False              # bỏ ô nền trắng/đen
    pixel_smart_skip: bool = True            # chụp canvas, chỉ vẽ ô sai màu
    pixel_color_tolerance: int = 24          # ngưỡng sai số màu cho smart skip
    pixel_batch_size: int = 0                # 0 = vẽ hết; >0 = giới hạn ô/lần
    pixel_offset_x: int = 0                  # tọa độ ô bắt đầu vẽ (góc trên-trái ảnh trên canvas)
    pixel_offset_y: int = 0                  # vd offset_x=100 -> ảnh vẽ từ cột 100 sang phải
    pixel_image_path: str = ""               # ảnh nguồn để vẽ
    pixel_progress_path: str = ""            # file lưu tiến độ (rỗng = mặc định)
    pixel_canvas_origin_x: float = 0         # 0 = tự dò canvas
    pixel_canvas_origin_y: float = 0
    pixel_cell_w: float = 0
    pixel_cell_h: float = 0
    # --- Screen mode (điều khiển chuột thật trên trình duyệt đã login) ---
    pixel_use_screen_mode: bool = True       # True = chuột thật trên màn hình; False = Playwright mở URL
    # --- DOM mode (Playwright mở Chrome riêng, click element DOM — KHÔNG cần focus) ---
    pixel_use_dom_mode: bool = False         # True = DOM mode (khuyên dùng khi web khóa focus)
    pixel_screen_canvas_x1: int = 0          # toạ độ góc trên-trái canvas (màn hình vật lý)
    pixel_screen_canvas_y1: int = 0
    pixel_screen_canvas_x2: int = 0          # toạ độ góc dưới-phải canvas
    pixel_screen_canvas_y2: int = 0
    pixel_screen_palette_x1: int = 0         # toạ độ góc trên-trái vùng palette
    pixel_screen_palette_y1: int = 0
    pixel_screen_palette_x2: int = 0         # toạ độ góc dưới-phải vùng palette
    pixel_screen_palette_y2: int = 0
    pixel_start_delay_seconds: float = 5.0   # đếm ngược trước khi bắt đầu vẽ (để bạn chuyển sang Chrome)

    # --- Khác ---
    headless: bool = False                   # chạy ẩn hay hiện


def default_paths() -> tuple[str, str]:
    base = os.path.dirname(os.path.abspath(__file__))
    return (
        os.path.join(base, "screenshots"),
        os.path.join(base, "session"),
    )


def load() -> Config:
    if not os.path.exists(CONFIG_PATH):
        cfg = Config()
        sc, ss = default_paths()
        cfg.screenshot_root = sc
        cfg.session_dir = ss
        save(cfg)
        return cfg
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    sc, ss = default_paths()
    data.setdefault("screenshot_root", sc)
    data.setdefault("session_dir", ss)
    return Config(**{k: v for k, v in data.items() if k in Config.__dataclass_fields__})


def save(cfg: Config) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(asdict(cfg), f, allow_unicode=True, sort_keys=False)


def today_folder(screenshot_root: str) -> str:
    """Trả về đường dẫn thư mục cho ngày hôm nay (DD.M.YY)."""
    name = datetime.now().strftime("%d.%-m.%y") if os.name != "nt" else datetime.now().strftime("%d.%#m.%y")
    path = os.path.join(screenshot_root, name)
    os.makedirs(path, exist_ok=True)
    return path
