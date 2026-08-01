"""Engine chính: quản lý trình duyệt, lên lịch và thực thi tác vụ."""
from __future__ import annotations

import os
import threading
import time
from datetime import datetime, time as dtime
from typing import Callable, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

import browser
import fb_tasks
import msg_tasks
from config import Config, load, save
from pdf_pages import PdfPager


def parse_hhmm(s: str) -> dtime:
    h, m = s.split(":")
    return dtime(int(h), int(m))


class Engine:
    """Chạy nền: mở 1 trình duyệt dùng chung và lên lịch 2 tác vụ."""

    def __init__(self, cfg: Config, log: Callable[[str], None] = print):
        self.cfg = cfg
        self.log = log
        self.scheduler: Optional[BackgroundScheduler] = None
        self._lock = threading.Lock()
        self._stop_evt = threading.Event()
        self.pager: Optional[PdfPager] = None
        self.mgr: Optional[browser.BrowserManager] = None

    # ---------- Vòng đời ----------
    def start(self) -> None:
        save(self.cfg)  # lưu lại config mới nhất
        if self.cfg.pdf_path and self.cfg.send_pdf:
            self.pager = PdfPager(self.cfg.pdf_path, self.cfg.start_page)
        self.mgr = browser.BrowserManager(self.cfg.session_dir, headless=self.cfg.headless)
        self.mgr.start()
        self._schedule()
        self.log(f"[Engine] Đã khởi động. Lịch: {self.cfg.start_time}–{self.cfg.end_time}, "
                 f"FB mỗi {self.cfg.fb_interval_minutes}p, MSG mỗi {self.cfg.msg_interval_minutes}p.")
        try:
            while not self._stop_evt.is_set():
                time.sleep(1)
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        self.log("[Engine] Đang dừng...")
        if self.scheduler:
            try:
                self.scheduler.shutdown(wait=False)
            except Exception:
                pass
            self.scheduler = None
        if self.mgr:
            self.mgr.close()
            self.mgr = None
        self._stop_evt.set()

    def stop(self) -> None:
        self._stop_evt.set()

    # ---------- Lịch ----------
    def _schedule(self) -> None:
        sched = BackgroundScheduler()
        start = parse_hhmm(self.cfg.start_time)
        end = parse_hhmm(self.cfg.end_time)
        # Cron theo phút bắt đầu và cứ mỗi `interval` phút, nhưng chỉ trong khoảng giờ
        fb_int = self.cfg.fb_interval_minutes
        msg_int = self.cfg.msg_interval_minutes

        # Tạo trigger theo phút: mỗi `fb_int` phút
        fb_trigger = CronTrigger(
            hour=f"{start.hour}-{end.hour}", minute=f"*/{fb_int}", second=0
        )
        sched.add_job(self._job_fb, fb_trigger, id="fb", max_instances=1, coalesce=True)
        self.log(f"[Engine] FB cron: hour={start.hour}-{end.hour} minute=*/{fb_int}")

        msg_trigger = CronTrigger(
            hour=f"{start.hour}-{end.hour}", minute=f"*/{msg_int}", second=0
        )
        sched.add_job(self._job_msg, msg_trigger, id="msg", max_instances=1, coalesce=True)
        self.log(f"[Engine] MSG cron: hour={start.hour}-{end.hour} minute=*/{msg_int}")
        sched.start()
        self.scheduler = sched

    # ---------- Tác vụ (chạy trong lock để không chồng chéo) ----------
    def _job_fb(self) -> None:
        now = datetime.now().time()
        if not (parse_hhmm(self.cfg.start_time) <= now <= parse_hhmm(self.cfg.end_time)):
            return
        with self._lock:
            if not self.mgr or self._stop_evt.is_set():
                return
            try:
                page = self.mgr.new_page()
                fb_tasks.comment_and_like(page, self.cfg, self.log)
                page.close()
            except Exception as e:
                self.log(f"[FB][Lỗi] {e}")

    def _job_msg(self) -> None:
        now = datetime.now().time()
        if not (parse_hhmm(self.cfg.start_time) <= now <= parse_hhmm(self.cfg.end_time)):
            return
        if self.pager is None:
            return
        with self._lock:
            if not self.mgr or self._stop_evt.is_set():
                return
            try:
                page = self.mgr.new_page()
                msg_tasks.send_pdf_page(page, self.cfg, self.pager, self.log)
                page.close()
            except Exception as e:
                self.log(f"[MSG][Lỗi] {e}")

    # ---------- Chạy thử ngay ----------
    def run_fb_now(self) -> None:
        threading.Thread(target=self._run_fb_once, daemon=True).start()

    def _run_fb_once(self) -> None:
        with self._lock:
            try:
                if not self.mgr:
                    self.mgr = browser.BrowserManager(self.cfg.session_dir, headless=self.cfg.headless)
                    self.mgr.start()
                page = self.mgr.new_page()
                fb_tasks.comment_and_like(page, self.cfg, self.log)
                page.close()
            except Exception as e:
                self.log(f"[FB][Lỗi] {e}")

    def run_msg_now(self) -> None:
        threading.Thread(target=self._run_msg_once, daemon=True).start()

    def _run_msg_once(self) -> None:
        with self._lock:
            try:
                if not self.mgr:
                    self.mgr = browser.BrowserManager(self.cfg.session_dir, headless=self.cfg.headless)
                    self.mgr.start()
                if self.pager is None and self.cfg.pdf_path:
                    self.pager = PdfPager(self.cfg.pdf_path, self.cfg.start_page)
                if self.pager is None:
                    self.log("[MSG] Chưa chọn file PDF.")
                    return
                page = self.mgr.new_page()
                msg_tasks.send_pdf_page(page, self.cfg, self.pager, self.log)
                page.close()
            except Exception as e:
                self.log(f"[MSG][Lỗi] {e}")

    # ---------- Pixel Painter (chạy theo nút, không cần lịch) ----------
    def run_pixel_now(self, batch_size: int = 0) -> None:
        threading.Thread(target=self._run_pixel_once, args=(batch_size,), daemon=True).start()

    def _run_pixel_once(self, batch_size: int = 0) -> None:
        with self._lock:
            try:
                import pixel_painter as pp
                if not self.mgr:
                    self.mgr = browser.BrowserManager(self.cfg.session_dir, headless=self.cfg.headless)
                    self.mgr.start()
                if not self.cfg.pixel_image_path or not os.path.exists(self.cfg.pixel_image_path):
                    self.log("[Pixel] Chưa chọn ảnh nguồn.")
                    return
                palette = pp.build_palette(self.cfg)
                plan = pp.PixelPlan.load(self.cfg.pixel_progress_path)
                if plan is None:
                    plan = pp.PixelPlan.from_image(self.cfg, palette)
                    self.log(f"[Pixel] Tạo plan mới: {len(plan.cells)} ô.")
                else:
                    self.log(f"[Pixel] Resume: {plan.index}/{len(plan.cells)} ô.")
                page = self.mgr.new_page()
                try:
                    page.goto(self.cfg.pixel_url, wait_until="domcontentloaded", timeout=60000)
                    page.wait_for_timeout(1500)
                    geo = pp.detect_canvas(page, self.cfg, self.log)
                    if not geo:
                        return
                    page_palette = pp.detect_palette(page, self.cfg, self.log)
                    pp.paint(page, self.cfg, plan, page_palette, geo,
                             log=self.log, batch_size=batch_size)
                finally:
                    page.close()
            except Exception as e:
                self.log(f"[Pixel][Lỗi] {e}")
