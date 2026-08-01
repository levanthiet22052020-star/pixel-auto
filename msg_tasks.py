"""Tác vụ gửi ảnh trang PDF qua Messenger + chụp + cắt."""
from __future__ import annotations

import os
from typing import Callable

from playwright.sync_api import Page, TimeoutError as PWTimeout

from config import Config, today_folder
from pdf_pages import PdfPager
import screenshot


def _human_delay(page: Page, lo: float = 0.4, hi: float = 1.2) -> None:
    page.wait_for_timeout(int(1000 * (lo + (hi - lo) * 0.5)))


def _open_chat(page: Page, cfg: Config, log) -> bool:
    """Mở đoạn chat với người nhận. Trả True nếu mở được ô nhập tin nhắn."""
    target = cfg.contact_name.strip()
    if target.startswith("http"):
        page.goto(target, wait_until="domcontentloaded", timeout=60000)
    else:
        page.goto("https://www.facebook.com/messages", wait_until="domcontentloaded", timeout=60000)
        _human_delay(page)
        # Tìm ô search
        try:
            search = page.wait_for_selector(
                'input[aria-label*="Tìm kiếm" i], input[placeholder*="Tìm kiếm" i]',
                timeout=8000,
            )
            search.click()
            page.keyboard.type(target, delay=40)
            page.wait_for_timeout(1500)
            page.keyboard.press("Enter")
            page.wait_for_timeout(2500)
        except PWTimeout:
            log(f"[MSG][Lỗi] Không tìm thấy ô tìm kiếm để mở chat '{target}'.")
            return False
    _human_delay(page)
    # Xác nhận có ô nhập tin nhắn
    try:
        page.wait_for_selector(
            'div[role="main"] [contenteditable="true"], '
            '[aria-label*="Tin nhắn" i][contenteditable="true"]',
            timeout=10000,
        )
        return True
    except PWTimeout:
        log("[MSG][Lỗi] Không thấy ô nhập tin nhắn. Có thể chưa mở đúng đoạn chat.")
        return False


def send_pdf_page(
    page: Page,
    cfg: Config,
    pager: PdfPager,
    log: Callable[[str], None] = print,
) -> str | None:
    """Render trang PDF hiện tại → gửi ảnh vào Messenger → chụp + cắt. Trả đường dẫn ảnh."""
    if not pager.has_more():
        log(f"[MSG] Đã gửi hết PDF ({pager.page_count} trang).")
        return None

    img_path = pager.render_current()
    log(f"[MSG] Render trang {pager.current}/{pager.page_count}: {os.path.basename(img_path)}")

    if not _open_chat(page, cfg, log):
        return None

    # Nút thêm ảnh / đính kèm
    attach_selectors = [
        'div[role="button"][aria-label*="Ảnh" i]',
        'div[role="button"][aria-label*="Photo" i]',
        'label input[type="file"][accept*="image"]',
    ]
    file_input = None
    # Thử trực tiếp input file ẩn trước
    try:
        file_input = page.query_selector('input[type="file"][accept*="image"]')
    except Exception:
        pass

    if file_input is None:
        for sel in attach_selectors:
            try:
                btn = page.query_selector(sel)
                if btn and "input" not in sel:
                    btn.click()
                    _human_delay(page)
                file_input = page.wait_for_selector(
                    'input[type="file"][accept*="image"]', timeout=5000
                )
                if file_input:
                    break
            except PWTimeout:
                continue

    if file_input is None:
        log("[MSG][Lỗi] Không tìm thấy cách đính kèm ảnh.")
        return None

    file_input.set_input_files(img_path)
    log("[MSG] Đã chọn ảnh, chờ tải lên...")
    page.wait_for_timeout(4000)

    # Gửi
    try:
        send_btn = page.query_selector(
            'div[role="button"][aria-label*="Gửi" i], '
            'div[role="button"][aria-label*="Send" i]'
        )
        if send_btn:
            send_btn.click()
        else:
            page.keyboard.press("Enter")
        page.wait_for_timeout(3000)
    except Exception as e:
        log(f"[MSG][Cảnh báo] Gửi tin nhắn: {e}")

    # Chụp full màn hình rồi cắt sidebar trái nếu cấu hình
    img = screenshot.grab_full_screen()
    if cfg.crop_messenger_left:
        img = screenshot.crop_left_sidebar(img, cut_ratio=0.30)
    folder = today_folder(cfg.screenshot_root)
    path = screenshot.save_screenshot(img, folder, "msg")
    log(f"[MSG] Đã lưu ảnh: {path}")

    # Sang trang kế cho lần sau
    pager.advance()
    try:
        os.remove(img_path)
    except OSError:
        pass
    return path
