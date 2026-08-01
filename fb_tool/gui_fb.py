"""Giao diện đồ họa (Tkinter) cho tool Auto Check-in Facebook + Messenger.

Tách riêng từ gui.py gốc — chỉ giữ phần Facebook/Messenger (bỏ Pixel Art).
"""
from __future__ import annotations

import queue
import threading
from tkinter import (
    Tk, ttk, StringVar, BooleanVar, IntVar, filedialog, messagebox, scrolledtext,
)
from tkinter.constants import *

import config as cfgmod
from config import Config
from core import Engine


class App:
    def __init__(self, root: Tk):
        self.root = root
        self.root.title("Auto Check-in Facebook + Messenger")
        self.root.geometry("820x720")
        self.root.minsize(760, 600)
        self.cfg = cfgmod.load()
        self.engine: Engine | None = None
        self.log_queue: queue.Queue[str] = queue.Queue()

        # Biến ràng buộc
        self.page_url = StringVar(value=self.cfg.page_url)
        self.comment_template = StringVar(value=self.cfg.comment_template)
        self.like_after = BooleanVar(value=self.cfg.like_after_comment)
        self.contact_name = StringVar(value=self.cfg.contact_name)
        self.send_pdf = BooleanVar(value=self.cfg.send_pdf)
        self.pdf_path = StringVar(value=self.cfg.pdf_path)
        self.start_page = IntVar(value=self.cfg.start_page)
        self.start_time = StringVar(value=self.cfg.start_time)
        self.end_time = StringVar(value=self.cfg.end_time)
        self.fb_interval = IntVar(value=self.cfg.fb_interval_minutes)
        self.msg_interval = IntVar(value=self.cfg.msg_interval_minutes)
        self.crop_left = BooleanVar(value=self.cfg.crop_messenger_left)
        self.headless = BooleanVar(value=self.cfg.headless)

        self._build_ui()
        self._poll_logs()
        # Tự lưu cấu hình khi đóng cửa sổ.
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------------- UI ----------------
    def _build_ui(self):
        pad = {"padx": 8, "pady": 4}
        n = ttk.Notebook(self.root)
        n.pack(fill=BOTH, expand=True, padx=8, pady=8)

        # Tab Cài đặt
        tab = ttk.Frame(n)
        n.add(tab, text="1. Cài đặt")

        # Facebook
        fb = ttk.LabelFrame(tab, text="Facebook")
        fb.pack(fill=X, **pad)
        ttk.Label(fb, text="Link trang FB:").grid(row=0, column=0, sticky=W, padx=6, pady=4)
        ttk.Entry(fb, textvariable=self.page_url, width=60).grid(
            row=0, column=1, sticky=EW, padx=6, pady=4
        )
        ttk.Label(fb, text="Mẫu comment:").grid(row=1, column=0, sticky=W, padx=6, pady=4)
        ttk.Entry(fb, textvariable=self.comment_template, width=60).grid(
            row=1, column=1, sticky=EW, padx=6, pady=4
        )
        ttk.Label(
            fb,
            text="Biến: {hh}:{mm} = giờ:phút • {d}.{m}.{yy} = ngày.tháng.năm",
            foreground="gray",
        ).grid(row=2, column=1, sticky=W, padx=6)
        ttk.Checkbutton(fb, text="Like bài sau khi comment", variable=self.like_after).grid(
            row=3, column=1, sticky=W, padx=6, pady=4
        )
        fb.columnconfigure(1, weight=1)

        # Messenger
        ms = ttk.LabelFrame(tab, text="Messenger")
        ms.pack(fill=X, **pad)
        ttk.Label(ms, text="Người nhận (tên hoặc link):").grid(row=0, column=0, sticky=W, padx=6, pady=4)
        ttk.Entry(ms, textvariable=self.contact_name, width=60).grid(
            row=0, column=1, sticky=EW, padx=6, pady=4
        )
        ttk.Checkbutton(ms, text="Gửi ảnh PDF qua Messenger", variable=self.send_pdf).grid(
            row=1, column=1, sticky=W, padx=6, pady=4
        )
        ttk.Checkbutton(
            ms, text="Cắt thanh bạn bè bên trái khi chụp", variable=self.crop_left
        ).grid(row=2, column=1, sticky=W, padx=6, pady=4)
        ms.columnconfigure(1, weight=1)

        # PDF
        pf = ttk.LabelFrame(tab, text="File PDF")
        pf.pack(fill=X, **pad)
        ttk.Label(pf, text="File PDF:").grid(row=0, column=0, sticky=W, padx=6, pady=4)
        row = ttk.Frame(pf)
        row.grid(row=0, column=1, sticky=EW, padx=6, pady=4)
        ttk.Entry(row, textvariable=self.pdf_path, width=45).pack(side=LEFT, fill=X, expand=True)
        ttk.Button(row, text="Chọn...", command=self._pick_pdf).pack(side=LEFT, padx=(4, 0))
        ttk.Label(pf, text="Trang bắt đầu:").grid(row=1, column=0, sticky=W, padx=6, pady=4)
        ttk.Spinbox(pf, from_=1, to=9999, textvariable=self.start_page, width=8).grid(
            row=1, column=1, sticky=W, padx=6, pady=4
        )
        pf.columnconfigure(1, weight=1)

        # Lịch
        sc = ttk.LabelFrame(tab, text="Lịch chạy")
        sc.pack(fill=X, **pad)
        ttk.Label(sc, text="Bắt đầu (HH:MM):").grid(row=0, column=0, sticky=W, padx=6, pady=4)
        ttk.Entry(sc, textvariable=self.start_time, width=8).grid(row=0, column=1, sticky=W, padx=6)
        ttk.Label(sc, text="Kết thúc (HH:MM):").grid(row=0, column=2, sticky=W, padx=6, pady=4)
        ttk.Entry(sc, textvariable=self.end_time, width=8).grid(row=0, column=3, sticky=W, padx=6)
        ttk.Label(sc, text="FB mỗi (phút):").grid(row=1, column=0, sticky=W, padx=6, pady=4)
        ttk.Spinbox(sc, from_=1, to=1440, textvariable=self.fb_interval, width=8).grid(
            row=1, column=1, sticky=W, padx=6
        )
        ttk.Label(sc, text="Messenger mỗi (phút):").grid(row=1, column=2, sticky=W, padx=6, pady=4)
        ttk.Spinbox(sc, from_=1, to=1440, textvariable=self.msg_interval, width=8).grid(
            row=1, column=3, sticky=W, padx=6
        )
        ttk.Checkbutton(sc, text="Ẩn trình duyệt (headless)", variable=self.headless).grid(
            row=2, column=0, columnspan=4, sticky=W, padx=6, pady=4
        )

        # Tab Nhật ký
        log_tab = ttk.Frame(n)
        n.add(log_tab, text="2. Nhật ký")
        self.log_box = scrolledtext.ScrolledText(log_tab, height=20, wrap=WORD, font=("Consolas", 9))
        self.log_box.pack(fill=BOTH, expand=True, padx=8, pady=8)

        # Nút điều khiển
        bar = ttk.Frame(self.root)
        bar.pack(fill=X, padx=8, pady=(0, 10))
        ttk.Button(bar, text="💾 Lưu cài đặt", command=self._save).pack(side=LEFT, padx=4)
        ttk.Button(bar, text="🔑 Đăng nhập FB", command=self._setup_session).pack(side=LEFT, padx=4)
        ttk.Button(bar, text="▶ Thử FB ngay", command=self._run_fb).pack(side=LEFT, padx=4)
        ttk.Button(bar, text="▶ Thử Messenger ngay", command=self._run_msg).pack(side=LEFT, padx=4)
        self.btn_start = ttk.Button(bar, text="▶ BẮT ĐẦU CHẠY", command=self._start_engine)
        self.btn_start.pack(side=LEFT, padx=4)
        self.btn_stop = ttk.Button(bar, text="⏹ DỪNG", command=self._stop_engine, state=DISABLED)
        self.btn_stop.pack(side=LEFT, padx=4)

        self.status = StringVar(value="Sẵn sàng.")
        ttk.Label(self.root, textvariable=self.status, anchor=W).pack(fill=X, padx=12)

    # ---------------- Hành động ----------------
    def _pick_pdf(self):
        path = filedialog.askopenfilename(
            title="Chọn file PDF",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
        )
        if path:
            self.pdf_path.set(path)

    def _collect(self) -> Config:
        c = self.cfg
        c.page_url = self.page_url.get().strip()
        c.comment_template = self.comment_template.get().strip()
        c.like_after_comment = bool(self.like_after.get())
        c.contact_name = self.contact_name.get().strip()
        c.send_pdf = bool(self.send_pdf.get())
        c.pdf_path = self.pdf_path.get().strip()
        c.start_page = int(self.start_page.get())
        c.start_time = self.start_time.get().strip()
        c.end_time = self.end_time.get().strip()
        c.fb_interval_minutes = int(self.fb_interval.get())
        c.msg_interval_minutes = int(self.msg_interval.get())
        c.crop_messenger_left = bool(self.crop_left.get())
        c.headless = bool(self.headless.get())
        return c

    def _save(self):
        cfgmod.save(self._collect())
        self._log("Đã lưu cài đặt vào config.yaml.")

    def _setup_session(self):
        self._save()
        c = self._collect()
        if not messagebox.askyesno(
            "Đăng nhập", "Sẽ mở Chrome để bạn đăng nhập Facebook.\nĐăng nhập xong hãy ĐÓNG trình duyệt để lưu.\nTiếp tục?"
        ):
            return

        def work():
            try:
                import browser as br
                br.setup_session(c.session_dir)
                self._log("✅ Đã lưu phiên đăng nhập.")
            except Exception as e:
                self._log(f"❌ Lỗi setup: {e}")
        threading.Thread(target=work, daemon=True).start()

    def _run_fb(self):
        if self.engine:
            self.engine.run_fb_now()
            self._log("Đang chạy thử FB...")
        else:
            self._quick_run(fb=True)

    def _run_msg(self):
        if self.engine:
            self.engine.run_msg_now()
            self._log("Đang chạy thử Messenger...")
        else:
            self._quick_run(fb=False)

    def _quick_run(self, fb: bool):
        self._save()
        c = self._collect()

        def work():
            eng = Engine(c, log=self._log)
            try:
                import browser as br
                mgr = br.BrowserManager(c.session_dir, headless=c.headless)
                mgr.start()
                from playwright.sync_api import sync_playwright  # noqa
                page = mgr.new_page()
                if fb:
                    import fb_tasks
                    fb_tasks.comment_and_like(page, c, self._log)
                else:
                    from pdf_pages import PdfPager
                    import msg_tasks
                    pager = PdfPager(c.pdf_path, c.start_page)
                    msg_tasks.send_pdf_page(page, c, pager, self._log)
                page.close()
                mgr.close()
                self._log("✅ Xong thử.")
            except Exception as e:
                self._log(f"❌ Lỗi: {e}")
        threading.Thread(target=work, daemon=True).start()

    def _start_engine(self):
        self._save()
        c = self._collect()
        if not c.page_url:
            messagebox.showwarning("Thiếu", "Vui lòng nhập link trang Facebook.")
            return
        if self.engine:
            return
        self.engine = Engine(c, log=self._log)
        threading.Thread(target=self._engine_thread, daemon=True).start()
        self.btn_start.config(state=DISABLED)
        self.btn_stop.config(state=NORMAL)
        self.status.set("Đang chạy theo lịch.")

    def _engine_thread(self):
        try:
            self.engine.start()
        except Exception as e:
            self._log(f"❌ Lỗi engine: {e}")
        finally:
            self.engine = None
            self.root.after(0, lambda: self.btn_start.config(state=NORMAL))
            self.root.after(0, lambda: self.btn_stop.config(state=DISABLED))
            self.root.after(0, lambda: self.status.set("Đã dừng."))

    def _stop_engine(self):
        if self.engine:
            self.engine.stop()
            self._log("Đang dừng engine...")

    def _on_close(self):
        """Tự lưu cấu hình khi đóng cửa sổ để mở lại không phải nhập lại."""
        try:
            self._save()
        except Exception:
            pass
        try:
            if self.engine:
                self.engine.stop()
        except Exception:
            pass
        self.root.destroy()

    # ---------------- Logging ----------------
    def _log(self, msg: str):
        self.log_queue.put(str(msg))

    def _poll_logs(self):
        try:
            while True:
                msg = self.log_queue.get_nowait()
                self.log_box.insert(END, msg + "\n")
                self.log_box.see(END)
        except queue.Empty:
            pass
        self.root.after(200, self._poll_logs)


def main():
    root = Tk()
    try:
        style = ttk.Style()
        style.theme_use("vista")
    except Exception:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
