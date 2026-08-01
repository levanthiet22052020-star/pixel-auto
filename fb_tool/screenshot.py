"""Tiện ích chụp màn hình và cắt ảnh."""
from __future__ import annotations

import os
from datetime import datetime

import mss
from PIL import Image


def grab_full_screen() -> Image.Image:
    """Chụp toàn bộ màn hình desktop (kèm taskbar có đồng hồ)."""
    with mss.mss() as sct:
        monitor = sct.monitors[1]  # màn hình chính
        raw = sct.grab(monitor)
        img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
    return img


def crop_left_sidebar(img: Image.Image, cut_ratio: float = 0.30) -> Image.Image:
    """Cắt bỏ phần sidebar bên trái (danh sách bạn bè/chat).

    cut_ratio: tỉ lệ chiều rộng bị cắt (mặc định 30% bên trái).
    """
    w, h = img.size
    left = int(w * cut_ratio)
    return img.crop((left, 0, w, h))


def save_screenshot(img: Image.Image, folder: str, prefix: str) -> str:
    """Lưu ảnh vào folder, tên dạng prefix_HH-MM.png. Trả về đường dẫn."""
    os.makedirs(folder, exist_ok=True)
    stamp = datetime.now().strftime("%H-%M")
    path = os.path.join(folder, f"{prefix}_{stamp}.png")
    img.save(path, "PNG")
    return path
