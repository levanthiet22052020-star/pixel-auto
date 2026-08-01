"""Quản lý trình duyệt Chrome và phiên đăng nhập Facebook bằng Playwright.

Dùng persistent context để giữ cookie/phiên đăng nhập giữa các lần chạy.
"""
from __future__ import annotations

import os

from playwright.sync_api import sync_playwright, BrowserContext, Page


# User-Agent thật để Facebook không đánh dấu là bot
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
)


class BrowserManager:
    def __init__(self, session_dir: str, headless: bool = False):
        self.session_dir = session_dir
        self.headless = headless
        self._pw = None
        self._context: BrowserContext | None = None

    def start(self) -> BrowserContext:
        os.makedirs(self.session_dir, exist_ok=True)
        self._pw = sync_playwright().start()
        # Dùng Chrome thật đã cài trên máy (channel="chrome") thay vì Chromium dev.
        # Ổn định hơn, không bị web nhận diện là automation, không nhấp nháy tắt.
        launch_kwargs = dict(
            user_data_dir=self.session_dir,
            headless=self.headless,
            user_agent=UA,
            viewport={"width": 1366, "height": 768},
            locale="vi-VN",
            args=["--disable-blink-features=AutomationControlled"],
        )
        # Thử Chrome thật (channel=chrome) trước; nếu không có thì fallback Chromium.
        try:
            self._context = self._pw.chromium.launch_persistent_context(
                channel="chrome", **launch_kwargs
            )
        except Exception as e:
            print(f"[Browser] Không tìm thấy Chrome thật ({e}), dùng Chromium mặc định.")
            self._context = self._pw.chromium.launch_persistent_context(**launch_kwargs)
        return self._context

    def new_page(self) -> Page:
        if self._context is None:
            self.start()
        return self._context.new_page()

    @property
    def context(self) -> BrowserContext:
        if self._context is None:
            self.start()
        return self._context

    def close(self) -> None:
        try:
            if self._context:
                self._context.close()
        finally:
            if self._pw:
                self._pw.stop()
        self._context = None
        self._pw = None


def setup_session(session_dir: str) -> None:
    """Mở Chrome để người dùng tự đăng nhập Facebook lần đầu."""
    print("[Setup] Mở Chrome để đăng nhập Facebook.")
    print("[Setup] Sau khi đăng nhập xong, hãy ĐÓNG trình duyệt để lưu phiên.")
    mgr = BrowserManager(session_dir, headless=False)
    mgr.start()
    page = mgr.new_page()
    page.goto("https://www.facebook.com/login", wait_until="domcontentloaded")
    # Chờ người dùng đóng trình duyệt
    try:
        while not mgr.context.pages == []:
            page.wait_for_timeout(1000)
    except Exception:
        pass
    mgr.close()
    print("[Setup] Đã lưu phiên đăng nhập.")
