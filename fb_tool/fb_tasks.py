"""Tác vụ comment + Like trên trang Facebook."""
from __future__ import annotations

import os
from datetime import datetime
from typing import Callable

from playwright.sync_api import Page, TimeoutError as PWTimeout

from config import Config
import screenshot


def _build_comment(template: str) -> str:
    now = datetime.now()
    return template.format(
        hh=f"{now.hour:02d}", mm=f"{now.minute:02d}",
        d=now.day, m=now.month, yy=f"{now.year % 100:02d}",
    )


def _human_delay(page: Page, lo: float = 0.4, hi: float = 1.0) -> None:
    page.wait_for_timeout(int(1000 * (lo + (hi - lo) * 0.5)))


def comment_and_like(
    page: Page,
    cfg: Config,
    log: Callable[[str], None] = print,
) -> str | None:
    """Mở trang FB → comment bài mới nhất → Like → chụp full màn hình.

    Trả về đường dẫn ảnh chụp (hoặc None nếu lỗi).
    """
    page.goto(cfg.page_url, wait_until="domcontentloaded", timeout=60000)
    _human_delay(page)
    page.wait_for_timeout(2500)

    text = _build_comment(cfg.comment_template)
    log(f"[FB] Comment: {text}")

    # Tìm bài đăng đầu tiên (mới nhất). FB dùng nhiều cấu trúc DOM khác nhau,
    # nên thử nhiều selector.
    comment_box_selectors = [
        'div[role="main"] [contenteditable="true"][data-contents="true"]',
        '[aria-label*="Viết bình luận" i]',
        '[aria-label*="Write a comment" i]',
        '[contenteditable="true"][aria-label*="comment" i]',
    ]
    box = None
    for sel in comment_box_selectors:
        try:
            box = page.wait_for_selector(sel, timeout=7000)
            break
        except PWTimeout:
            continue
    if box is None:
        log("[FB][Lỗi] Không tìm thấy ô bình luận. Có thể hết phiên hoặc đổi giao diện.")
        return None

    box.click()
    _human_delay(page)
    page.keyboard.type(text, delay=50)
    _human_delay(page)
    page.keyboard.press("Enter")
    page.wait_for_timeout(2000)

    # Like bài đăng
    if cfg.like_after_comment:
        try:
            like_btn = page.query_selector(
                'div[role="button"][aria-label*="Thích" i], '
                'div[role="button"][aria-label*="Like" i]'
            )
            if like_btn:
                like_btn.click()
                page.wait_for_timeout(1500)
                log("[FB] Đã Like.")
        except Exception as e:
            log(f"[FB][Cảnh báo] Không Like được: {e}")

    # Chụp full màn hình desktop (kèm đồng hồ)
    img = screenshot.grab_full_screen()
    from config import today_folder
    folder = today_folder(cfg.screenshot_root)
    path = screenshot.save_screenshot(img, folder, "fb")
    log(f"[FB] Đã lưu ảnh: {path}")
    return path
