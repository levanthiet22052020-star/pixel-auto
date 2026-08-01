"""Giao diện đồ họa (Tkinter) cho tool Pixel Painter.

Tách riêng từ gui.py gốc — chỉ giữ phần Pixel Art (bỏ Facebook/Messenger).
"""
from __future__ import annotations

import os
import queue
import threading
from tkinter import (
    Tk, ttk, StringVar, BooleanVar, IntVar, DoubleVar, filedialog, messagebox, scrolledtext, Canvas,
)
from tkinter.constants import *

import config as cfgmod
from config import Config


class App:
    def __init__(self, root: Tk):
        self.root = root
        self.root.title("Pixel Painter")
        self.root.geometry("820x860")
        self.root.minsize(760, 660)
        self.cfg = cfgmod.load()
        self.log_queue: queue.Queue[str] = queue.Queue()

        # Biến ràng buộc — Pixel Painter
        self.px_url = StringVar(value=self.cfg.pixel_url)
        self.px_grid_w = IntVar(value=self.cfg.pixel_grid_w)
        self.px_grid_h = IntVar(value=self.cfg.pixel_grid_h)
        self.px_offset_x = IntVar(value=getattr(self.cfg, "pixel_offset_x", 0))
        self.px_offset_y = IntVar(value=getattr(self.cfg, "pixel_offset_y", 0))
        self.px_cooldown = StringVar(value=str(self.cfg.pixel_cooldown_seconds))
        self.px_jitter = StringVar(value=str(self.cfg.pixel_jitter_seconds))
        self.px_palette = StringVar(value=self.cfg.pixel_palette_path)
        self.px_dither = BooleanVar(value=self.cfg.pixel_dither)
        self.px_bg_skip = BooleanVar(value=self.cfg.pixel_bg_skip)
        self.px_smart_skip = BooleanVar(value=self.cfg.pixel_smart_skip)
        self.px_tolerance = IntVar(value=self.cfg.pixel_color_tolerance)
        self.px_batch = IntVar(value=self.cfg.pixel_batch_size)
        self.px_image = StringVar(value=self.cfg.pixel_image_path)
        # Login trang pixel (DOM mode)
        self.px_site_url = StringVar(value=self.cfg.pixel_site_url)
        self.px_username = StringVar(value=self.cfg.pixel_username)
        self.px_password = StringVar(value=self.cfg.pixel_password)
        self.px_wait_login = BooleanVar(value=self.cfg.pixel_wait_for_login)
        # Screen mode
        self.px_screen_mode = BooleanVar(value=self.cfg.pixel_use_screen_mode)
        self.px_dom_mode = BooleanVar(value=self.cfg.pixel_use_dom_mode)
        self.px_cv_x1 = IntVar(value=self.cfg.pixel_screen_canvas_x1)
        self.px_cv_y1 = IntVar(value=self.cfg.pixel_screen_canvas_y1)
        self.px_cv_x2 = IntVar(value=self.cfg.pixel_screen_canvas_x2)
        self.px_cv_y2 = IntVar(value=self.cfg.pixel_screen_canvas_y2)
        self.px_pl_x1 = IntVar(value=self.cfg.pixel_screen_palette_x1)
        self.px_pl_y1 = IntVar(value=self.cfg.pixel_screen_palette_y1)
        self.px_pl_x2 = IntVar(value=self.cfg.pixel_screen_palette_x2)
        self.px_pl_y2 = IntVar(value=self.cfg.pixel_screen_palette_y2)
        self.px_start_delay = StringVar(value=str(self.cfg.pixel_start_delay_seconds))

        self._build_ui()
        self._poll_logs()
        self._setup_global_hotkey()
        # Tự lưu cấu hình khi đóng cửa sổ.
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------------- UI ----------------
    def _build_ui(self):
        pad = {"padx": 8, "pady": 4}
        n = ttk.Notebook(self.root)
        n.pack(fill=BOTH, expand=True, padx=8, pady=8)

        # Tab Pixel Art
        self._build_pixel_tab(n)

        # Tab Nhật ký
        log_tab = ttk.Frame(n)
        n.add(log_tab, text="2. Nhật ký")
        self.log_box = scrolledtext.ScrolledText(log_tab, height=20, wrap=WORD, font=("Consolas", 9))
        self.log_box.pack(fill=BOTH, expand=True, padx=8, pady=8)

        # Nút điều khiển
        bar = ttk.Frame(self.root)
        bar.pack(fill=X, padx=8, pady=(0, 10))
        ttk.Button(bar, text="💾 Lưu cài đặt", command=self._save).pack(side=LEFT, padx=4)
        self.status = StringVar(value="Sẵn sàng.")
        ttk.Label(self.root, textvariable=self.status, anchor=W).pack(fill=X, padx=12)

    # ---------------- Pixel Art tab ----------------
    def _build_pixel_tab(self, n: ttk.Notebook):
        pad = {"padx": 8, "pady": 4}
        outer = ttk.Frame(n)
        n.add(outer, text="1. Pixel Art")

        canvas = Canvas(outer, highlightthickness=0, borderwidth=0)
        vsb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=RIGHT, fill=Y)
        canvas.pack(side=LEFT, fill=BOTH, expand=True)
        tab = ttk.Frame(canvas)
        win_id = canvas.create_window((0, 0), window=tab, anchor="nw")

        def _on_wheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _on_wheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

        def _on_configure(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfigure(win_id, width=event.width)
        canvas.bind("<Configure>", _on_configure)

        # Nguồn ảnh
        src = ttk.LabelFrame(tab, text="Ảnh nguồn")
        src.pack(fill=X, **pad)
        ttk.Label(src, text="Ảnh:").grid(row=0, column=0, sticky=W, padx=6, pady=4)
        row = ttk.Frame(src)
        row.grid(row=0, column=1, sticky=EW, padx=6, pady=4)
        ttk.Entry(row, textvariable=self.px_image, width=42).pack(side=LEFT, fill=X, expand=True)
        ttk.Button(row, text="Chọn ảnh...", command=self._pick_pixel_image).pack(side=LEFT, padx=(4, 0))
        ttk.Button(row, text="🖼 Xem preview", command=self._pixel_preview).pack(side=LEFT, padx=(4, 0))
        src.columnconfigure(1, weight=1)

        # Chế độ điều khiển
        mode = ttk.LabelFrame(tab, text="Chế độ điều khiển")
        mode.pack(fill=X, **pad)
        self.px_mode_choice = StringVar(
            value="dom" if self.cfg.pixel_use_dom_mode
            else ("screen" if self.cfg.pixel_use_screen_mode else "url")
        )

        def _sync_mode(*_):
            choice = self.px_mode_choice.get()
            self.px_dom_mode.set(choice == "dom")
            self.px_screen_mode.set(choice == "screen")
        self.px_mode_choice.trace_add("write", _sync_mode)

        ttk.Radiobutton(
            mode, variable=self.px_mode_choice, value="dom",
            text="🟢 DOM mode (KHUYÊN DÙNG) — Playwright mở Chrome riêng, click element ô. "
                 "Web không bị khóa khi bạn tab đi chỗ khác.",
        ).grid(row=0, column=0, columnspan=4, sticky=W, padx=6, pady=2)
        ttk.Radiobutton(
            mode, variable=self.px_mode_choice, value="screen",
            text="🖥 Screen mode — chuột thật trên trình duyệt đang mở (cần giữ focus).",
        ).grid(row=1, column=0, columnspan=4, sticky=W, padx=6, pady=2)
        ttk.Radiobutton(
            mode, variable=self.px_mode_choice, value="url",
            text="🌐 URL/Playwright — click theo toạ độ canvas trên trang.",
        ).grid(row=2, column=0, columnspan=4, sticky=W, padx=6, pady=2)
        ttk.Label(mode, text="Chờ (giây) trước khi vẽ (screen mode):", foreground="gray").grid(
            row=3, column=0, sticky=W, padx=6, pady=4)
        ttk.Entry(mode, textvariable=self.px_start_delay, width=6).grid(row=3, column=1, sticky=W, padx=6)

        # Canh vị trí (calibration)
        cal = ttk.LabelFrame(tab, text="Canh vị trí trên màn hình (screen mode)")
        cal.pack(fill=X, **pad)
        ttk.Label(cal, text="Canvas (góc trên-trái → dưới-phải):", foreground="gray").grid(
            row=0, column=0, columnspan=5, sticky=W, padx=6, pady=(4, 0))
        ttk.Label(cal, text="X1:").grid(row=1, column=0, sticky=W, padx=6, pady=4)
        ttk.Entry(cal, textvariable=self.px_cv_x1, width=7).grid(row=1, column=1, sticky=W, padx=2)
        ttk.Label(cal, text="Y1:").grid(row=1, column=2, sticky=W, padx=6)
        ttk.Entry(cal, textvariable=self.px_cv_y1, width=7).grid(row=1, column=3, sticky=W, padx=2)
        ttk.Label(cal, text="X2:").grid(row=2, column=0, sticky=W, padx=6, pady=4)
        ttk.Entry(cal, textvariable=self.px_cv_x2, width=7).grid(row=2, column=1, sticky=W, padx=2)
        ttk.Label(cal, text="Y2:").grid(row=2, column=2, sticky=W, padx=6)
        ttk.Entry(cal, textvariable=self.px_cv_y2, width=7).grid(row=2, column=3, sticky=W, padx=2)
        ttk.Button(cal, text="🎯 Canh canvas (bấm rồi click 2 góc)",
                   command=lambda: self._calibrate_canvas()).grid(
            row=1, column=4, rowspan=2, sticky=N + S, padx=6, pady=4)

        ttk.Label(cal, text="Palette (vùng bảng màu):", foreground="gray").grid(
            row=3, column=0, columnspan=5, sticky=W, padx=6, pady=(8, 0))
        ttk.Label(cal, text="X1:").grid(row=4, column=0, sticky=W, padx=6, pady=4)
        ttk.Entry(cal, textvariable=self.px_pl_x1, width=7).grid(row=4, column=1, sticky=W, padx=2)
        ttk.Label(cal, text="Y1:").grid(row=4, column=2, sticky=W, padx=6)
        ttk.Entry(cal, textvariable=self.px_pl_y1, width=7).grid(row=4, column=3, sticky=W, padx=2)
        ttk.Label(cal, text="X2:").grid(row=5, column=0, sticky=W, padx=6, pady=4)
        ttk.Entry(cal, textvariable=self.px_pl_x2, width=7).grid(row=5, column=1, sticky=W, padx=2)
        ttk.Label(cal, text="Y2:").grid(row=5, column=2, sticky=W, padx=6)
        ttk.Entry(cal, textvariable=self.px_pl_y2, width=7).grid(row=5, column=3, sticky=W, padx=2)
        ttk.Button(cal, text="🎨 Canh palette (bấm rồi click 2 góc)",
                   command=lambda: self._calibrate_palette()).grid(
            row=4, column=4, rowspan=2, sticky=N + S, padx=6, pady=4)
        cal.columnconfigure(4, weight=1)

        # Đăng nhập trang pixel (DOM mode)
        lg = ttk.LabelFrame(tab, text="Đăng nhập trang (DOM mode)")
        lg.pack(fill=X, **pad)
        ttk.Label(lg, text="URL trang chính:").grid(row=0, column=0, sticky=W, padx=6, pady=4)
        ttk.Entry(lg, textvariable=self.px_site_url, width=40).grid(row=0, column=1, sticky=EW, padx=6, pady=4)
        ttk.Label(lg, text="Tài khoản:").grid(row=1, column=0, sticky=W, padx=6, pady=4)
        ttk.Entry(lg, textvariable=self.px_username, width=20).grid(row=1, column=1, sticky=W, padx=6, pady=4)
        ttk.Label(lg, text="Mật khẩu:").grid(row=2, column=0, sticky=W, padx=6, pady=4)
        ttk.Entry(lg, textvariable=self.px_password, width=20, show="•").grid(row=2, column=1, sticky=W, padx=6, pady=4)
        ttk.Checkbutton(lg, text="Chờ mình đăng nhập thủ công (dùng khi có captcha/2FA)",
                        variable=self.px_wait_login).grid(row=3, column=1, sticky=W, padx=6, pady=2)
        ttk.Label(lg, text="DOM mode: tool tự đăng nhập → bấm 'vẽ pixel' → vào trang canvas.",
                  foreground="gray").grid(row=4, column=1, sticky=W, padx=6)
        lg.columnconfigure(1, weight=1)

        # URL trang pixel (cho chế độ URL/Playwright)
        cv = ttk.LabelFrame(tab, text="URL trang pixel (DOM & URL mode)")
        cv.pack(fill=X, **pad)
        ttk.Label(cv, text="URL trang pixel:").grid(row=0, column=0, sticky=W, padx=6, pady=4)
        ttk.Entry(cv, textvariable=self.px_url, width=50).grid(row=0, column=1, sticky=EW, padx=6, pady=4)
        ttk.Label(
            cv,
            text="DOM mode dùng URL trang chính để đăng nhập rồi tự vào trang pixel.",
            foreground="gray",
        ).grid(row=1, column=1, sticky=W, padx=6)
        cv.columnconfigure(1, weight=1)

        # Kích thước ảnh & vị trí
        gr = ttk.LabelFrame(tab, text="📏 Kích thước ảnh pixel & vị trí vẽ (canvas thật 384×240)")
        gr.pack(fill=X, **pad)
        ttk.Label(gr, text="Rộng ảnh (ô):").grid(row=0, column=0, sticky=W, padx=6, pady=4)
        ttk.Spinbox(gr, from_=2, to=384, textvariable=self.px_grid_w, width=8).grid(row=0, column=1, sticky=W, padx=6)
        ttk.Label(gr, text="Cao ảnh (ô):").grid(row=0, column=2, sticky=W, padx=6, pady=4)
        ttk.Spinbox(gr, from_=2, to=240, textvariable=self.px_grid_h, width=8).grid(row=0, column=3, sticky=W, padx=6)
        ttk.Label(gr, text="→ Vẽ từ ô X:").grid(row=1, column=0, sticky=W, padx=6, pady=4)
        ttk.Spinbox(gr, from_=0, to=383, textvariable=self.px_offset_x, width=8).grid(row=1, column=1, sticky=W, padx=6)
        ttk.Label(gr, text="Y:").grid(row=1, column=2, sticky=W, padx=6, pady=4)
        ttk.Spinbox(gr, from_=0, to=239, textvariable=self.px_offset_y, width=8).grid(row=1, column=3, sticky=W, padx=6)
        ttk.Label(gr, text="Cooldown (giây):").grid(row=2, column=0, sticky=W, padx=6, pady=4)
        ttk.Entry(gr, textvariable=self.px_cooldown, width=8).grid(row=2, column=1, sticky=W, padx=6)
        ttk.Label(gr, text="Nhiễu ± (giây):").grid(row=2, column=2, sticky=W, padx=6, pady=4)
        ttk.Entry(gr, textvariable=self.px_jitter, width=8).grid(row=2, column=3, sticky=W, padx=6)
        ttk.Label(gr, text="Vẽ từng mẻ (số ô):").grid(row=3, column=0, sticky=W, padx=6, pady=4)
        ttk.Spinbox(gr, from_=0, to=100000, textvariable=self.px_batch, width=8).grid(row=3, column=1, sticky=W, padx=6)
        ttk.Label(gr, text="0 = vẽ hết", foreground="gray").grid(row=3, column=2, columnspan=2, sticky=W, padx=6)
        self.px_size_info = StringVar(value="")
        ttk.Label(gr, textvariable=self.px_size_info, foreground="#1d4ed8",
                  wraplength=520).grid(row=4, column=0, columnspan=4, sticky=W, padx=6, pady=(4, 6))
        for sv in (self.px_grid_w, self.px_grid_h, self.px_offset_x, self.px_offset_y):
            sv.trace_add("write", lambda *_: self._update_size_info())

        # Tùy chọn vẽ
        opt = ttk.LabelFrame(tab, text="Tùy chọn")
        opt.pack(fill=X, **pad)
        ttk.Checkbutton(opt, text="Dithering (chấm điểm để tạo dải màu)", variable=self.px_dither).grid(
            row=0, column=0, sticky=W, padx=6, pady=4)
        ttk.Checkbutton(opt, text="Bỏ ô nền trắng/đen", variable=self.px_bg_skip).grid(
            row=0, column=1, sticky=W, padx=6, pady=4)
        ttk.Checkbutton(opt, text="Smart skip (chỉ vẽ ô sai màu)", variable=self.px_smart_skip).grid(
            row=1, column=0, sticky=W, padx=6, pady=4)
        ttk.Label(opt, text="Dung sai màu:").grid(row=1, column=1, sticky=W, padx=(20, 0), pady=4)
        ttk.Spinbox(opt, from_=0, to=128, textvariable=self.px_tolerance, width=6).grid(row=1, column=1, sticky=E, padx=30, pady=4)

        # Palette
        pl = ttk.LabelFrame(tab, text="Palette (để trống = tự dò / web-safe)")
        pl.pack(fill=X, **pad)
        row = ttk.Frame(pl)
        row.grid(row=0, column=0, sticky=EW, padx=6, pady=4, columnspan=2)
        ttk.Entry(row, textvariable=self.px_palette, width=42).pack(side=LEFT, fill=X, expand=True)
        ttk.Button(row, text="Chọn file...", command=self._pick_palette).pack(side=LEFT, padx=(4, 0))
        pl.columnconfigure(0, weight=1)

        # Tiến độ
        pf = ttk.LabelFrame(tab, text="Tiến độ")
        pf.pack(fill=X, **pad)
        self.px_progress = DoubleVar(value=0.0)
        self.px_progress_bar = ttk.Progressbar(pf, variable=self.px_progress, maximum=100.0)
        self.px_progress_bar.pack(fill=X, padx=6, pady=4)
        self.px_progress_label = StringVar(value="Chưa có tiến độ.")
        ttk.Label(pf, textvariable=self.px_progress_label, anchor=W).pack(fill=X, padx=6, pady=(0, 4))
        row = ttk.Frame(pf)
        row.pack(fill=X, padx=6, pady=(0, 6))
        ttk.Button(row, text="👁 Xem trước", command=self._pixel_preview).pack(side=LEFT, padx=4)
        ttk.Button(row, text="🧪 Test tool", command=self._pixel_run_selftest).pack(side=LEFT, padx=4)
        ttk.Button(row, text="🎯 Vẽ 1 ô thử", command=self._pixel_test_one).pack(side=LEFT, padx=4)
        ttk.Button(row, text="▶ Vẽ thử (mẻ)", command=self._pixel_paint_batch).pack(side=LEFT, padx=4)
        ttk.Button(row, text="▶ Vẽ tất cả", command=self._pixel_paint_all).pack(side=LEFT, padx=4)
        ttk.Button(row, text="⏹ Hủy (ESC)", command=self._pixel_cancel).pack(side=LEFT, padx=4)
        ttk.Button(row, text="🔄 Xóa tiến độ", command=self._pixel_reset).pack(side=LEFT, padx=4)

        self._pixel_cancel_flag = False
        try:
            self._update_size_info()
        except Exception:
            pass

    def _pick_pixel_image(self):
        path = filedialog.askopenfilename(
            title="Chọn ảnh nguồn",
            filetypes=[("Ảnh", "*.png *.jpg *.jpeg *.bmp *.gif *.webp"), ("All files", "*.*")],
        )
        if path:
            self.px_image.set(path)

    def _pick_palette(self):
        path = filedialog.askopenfilename(
            title="Chọn file palette",
            filetypes=[("Text", "*.txt"), ("All files", "*.*")],
        )
        if path:
            self.px_palette.set(path)

    def _pixel_paint_batch(self):
        self._pixel_paint(batch=True)

    def _pixel_paint_all(self):
        self._pixel_paint(batch=False)

    def _pixel_paint(self, batch: bool):
        c = self._collect()
        if not c.pixel_image_path or not os.path.exists(c.pixel_image_path):
            messagebox.showwarning("Thiếu ảnh", "Chọn ảnh nguồn trước.")
            return
        if c.pixel_use_dom_mode:
            if not c.pixel_url:
                messagebox.showwarning("Thiếu URL", "DOM mode cần URL trang pixel canvas.")
                return
        elif c.pixel_use_screen_mode:
            if not (c.pixel_screen_canvas_x1 or c.pixel_screen_canvas_x2
                    or c.pixel_screen_canvas_y1 or c.pixel_screen_canvas_y2):
                ok = messagebox.askyesno(
                    "Chưa canh canvas",
                    "Bạn chưa canh vị trí canvas.\nTiếp tục vẽ ngay không? (Tool sẽ "
                    "không biết canvas ở đâu.)\n\nKhuyên: bấm Hủy rồi 'Canh canvas' trước."
                )
                if not ok:
                    return
        else:
            if not c.pixel_url:
                messagebox.showwarning("Thiếu URL", "Nhập URL trang pixel canvas hoặc bật Screen mode.")
                return
        self._pixel_paint_with_cfg(c, batch)

    def _pixel_paint_with_cfg(self, c: Config, batch: bool):
        """Khởi chạy thread vẽ với config đã thu thập."""
        try:
            import screen_painter as sp
            sp.clear_stop()
        except Exception:
            pass
        self._pixel_cancel_flag = False
        if batch and c.pixel_batch_size <= 0:
            c.pixel_batch_size = 50  # mặc định vẽ thử 50 ô

        if c.pixel_use_dom_mode:
            threading.Thread(target=self._paint_dom, args=(c, batch), daemon=True).start()
        elif c.pixel_use_screen_mode:
            threading.Thread(target=self._paint_screen, args=(c, batch), daemon=True).start()
        else:
            threading.Thread(target=self._paint_playwright, args=(c, batch), daemon=True).start()

    def _paint_playwright(self, c: Config, batch: bool):
        try:
            import pixel_painter as pp
            import browser as br
            palette = pp.build_palette(c)
            plan = pp.PixelPlan.load(c.pixel_progress_path)
            if plan is None:
                plan = pp.PixelPlan.from_image(c, palette)
                self._log(f"[Pixel] Tạo plan mới: {len(plan.cells)} ô.")
            else:
                self._log(f"[Pixel] Resume: {plan.index}/{len(plan.cells)} ô.")
            mgr = br.BrowserManager(c.session_dir, headless=c.headless)
            mgr.start()
            try:
                page = mgr.new_page()
                page.goto(c.pixel_url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(1500)
                geo = pp.detect_canvas(page, c, self._log)
                if not geo:
                    self._log("[Pixel][Lỗi] Không dò thấy canvas.")
                    return
                page_palette = pp.detect_palette(page, c, self._log)
                total = len(plan.cells)
                batch_size = c.pixel_batch_size if batch else 0
                drawn = pp.paint(page, c, plan, page_palette, geo,
                                 log=self._log, batch_size=batch_size)
                done = plan.index
                pct = (done / total * 100.0) if total else 0.0
                self._set_pixel_progress(pct, f"Đã vẽ {drawn} ô đợt này • Tổng {done}/{total}.")
                page.close()
            finally:
                mgr.close()
        except Exception as e:
            self._log(f"[Pixel][Lỗi] {e}")

    def _paint_dom(self, c: Config, batch: bool):
        """DOM mode — Playwright mở Chrome, click element DOM. Không cần giữ focus."""
        try:
            import dom_painter as dp
            import pixel_painter as pp
            import browser as br
            palette = pp.build_palette(c)
            plan = pp.PixelPlan.load(c.pixel_progress_path)
            if plan is None:
                plan = pp.PixelPlan.from_image(c, palette)
                self._log(f"[DOM] Tạo plan mới: {len(plan.cells)} ô.")
            else:
                rt_info = ""
                if plan.rate_times:
                    rt_info = f" · {len(plan.rate_times)} ô trong 5 phút qua (rate-limit kế thừa)"
                self._log(f"[DOM] 📂 Resume: tiếp tục từ ô {plan.index}/{len(plan.cells)}{rt_info}")

            mgr = br.BrowserManager(c.session_dir, headless=False)
            mgr.start()
            try:
                page = mgr.new_page()
                ok = dp.login_and_open_canvas(page, c, self._log)
                if not ok:
                    self._log("[DOM] Không vào được trang canvas sau khi chờ. "
                              "Chrome vẫn mở — bạn có thể tự xử lý rồi chạy lại. "
                              "Nhấn ESC trên app để đóng.")
                    import screen_painter as sp
                    import time as _t
                    while not sp.is_stopped():
                        _t.sleep(1)
                    return
                ci = dp.get_canvas_info(page)
                if ci is None:
                    self._log("[DOM][Lỗi] Không thấy canvas. Chưa vào trang pixel?")
                    return
                self._log(f"[DOM] Canvas: {ci.canvas_w}×{ci.canvas_h}, "
                          f"ô {ci.cell_px_x:.0f}×{ci.cell_px_y:.0f}px.")
                page_palette = dp.read_palette(page)
                self._log(f"[DOM] Palette: {len(page_palette)} màu.")

                def on_progress(done: int, tot: int):
                    pct = (done / tot * 100.0) if tot else 0.0
                    self._set_pixel_progress(pct, f"Đã tô {done}/{tot} ô.")

                batch_size = c.pixel_batch_size if batch else 0
                drawn = dp.paint_dom(page, c, plan, ci, page_palette,
                                     log=self._log, batch_size=batch_size, on_progress=on_progress)
                total = len(plan.cells)
                self._set_pixel_progress(
                    (plan.index / total * 100.0) if total else 0.0,
                    f"Đã tô {drawn} ô đợt này • Tổng {plan.index}/{total}.")
                self._log("[DOM] Xong. Đang đóng Chrome...")
                page.close()
            finally:
                mgr.close()
        except Exception as e:
            self._log(f"[DOM][Lỗi] {e}")
        try:
            import screen_painter as sp
            import pixel_painter as pp
            if c.pixel_screen_palette_x1 or c.pixel_screen_palette_x2:
                preg = sp.PaletteRegion(
                    x=min(c.pixel_screen_palette_x1, c.pixel_screen_palette_x2),
                    y=min(c.pixel_screen_palette_y1, c.pixel_screen_palette_y2),
                    width=abs(c.pixel_screen_palette_x2 - c.pixel_screen_palette_x1),
                    height=abs(c.pixel_screen_palette_y2 - c.pixel_screen_palette_y1),
                )
                page_palette = sp.detect_palette_from_screen(preg)
                self._log(f"[Pixel] Dò được {len(page_palette)} màu từ vùng palette trên màn hình.")
            else:
                preg = None
                page_palette = pp.build_palette(c)
                self._log(f"[Pixel] Dùng palette cấu hình ({len(page_palette)} màu). "
                          "Khuyên canh vùng palette để chọn màu chính xác.")

            palette = pp.build_palette(c)
            plan = pp.PixelPlan.load(c.pixel_progress_path)
            if plan is None:
                plan = pp.PixelPlan.from_image(c, palette)
                self._log(f"[Pixel] Tạo plan mới: {len(plan.cells)} ô.")
            else:
                self._log(f"[Pixel] Resume: {plan.index}/{len(plan.cells)} ô.")

            canvas = sp.CanvasRegion.from_corners(
                c.pixel_screen_canvas_x1, c.pixel_screen_canvas_y1,
                c.pixel_screen_canvas_x2, c.pixel_screen_canvas_y2,
            )
            self._log(f"[Pixel] Canvas: {canvas.width}x{canvas.height} tại ({canvas.x},{canvas.y}).")

            delay = max(0.0, c.pixel_start_delay_seconds)
            for i in range(int(delay), 0, -1):
                self._set_pixel_progress(0.0, f"Bắt đầu sau {i}s... (chuyển sang Chrome ngay!)")
                import time as _t
                _t.sleep(1)
            self._set_pixel_progress(0.0, f"Đang vẽ... {plan.remaining()} ô còn lại.")

            total = len(plan.cells)

            def on_progress(done: int, tot: int):
                pct = (done / tot * 100.0) if tot else 0.0
                self._set_pixel_progress(pct, f"Đã vẽ {done}/{tot} ô.")

            batch_size = c.pixel_batch_size if batch else 0
            drawn = sp.paint_on_screen(
                c, plan, canvas, preg, page_palette,
                log=self._log, batch_size=batch_size, on_progress=on_progress,
            )
            self._set_pixel_progress(
                (plan.index / total * 100.0) if total else 0.0,
                f"Đã vẽ {drawn} ô đợt này • Tổng {plan.index}/{total}.",
            )
        except Exception as e:
            self._log(f"[Pixel][Lỗi] {e}")

    # ---------------- Canh vị trí (calibration) ----------
    def _calibrate_canvas(self):
        self._pick_region_into(
            self.px_cv_x1, self.px_cv_y1, self.px_cv_x2, self.px_cv_y2,
            "Canh canvas — KÉO chuột qua vùng lưới pixel",
        )

    def _calibrate_palette(self):
        self._pick_region_into(
            self.px_pl_x1, self.px_pl_y1, self.px_pl_x2, self.px_pl_y2,
            "Canh palette — KÉO chuột qua vùng bảng màu",
        )

    def _pick_region_into(self, x1v, y1v, x2v, y2v, title: str):
        self._log(f"[Pixel] {title} — kéo thả chuột để chọn vùng (ESC để bỏ qua).")
        self._set_status(f"{title}...")

        def work():
            try:
                from region_picker import pick_region
                box = pick_region(title)
                if box is None:
                    self._set_status("Đã bỏ qua canh vị trí.")
                    return
                x1, y1, x2, y2 = box
                x1v.set(x1); y1v.set(y1)
                x2v.set(x2); y2v.set(y2)
                w = abs(x2 - x1)
                h = abs(y2 - y1)
                self._set_status(f"Đã canh: ({x1},{y1})→({x2},{y2}), vùng {w}×{h}px.")
                self._log(f"[Pixel] Đã canh ({x1},{y1})→({x2},{y2}), vùng {w}×{h}px.")
            except Exception as e:
                self._log(f"[Pixel][Canh] lỗi: {e}")
                self._set_status(f"Lỗi canh: {e}")

        threading.Thread(target=work, daemon=False).start()

    def _set_status(self, msg: str):
        try:
            self.root.after(0, lambda: self.status.set(msg))
        except Exception:
            pass

    def _pixel_cancel(self):
        self._pixel_cancel_flag = True
        try:
            import screen_painter as sp
            sp.request_stop()
        except Exception:
            pass
        self._log("[Pixel] ⏹ Đã yêu cầu dừng (ESC). Sẽ dừng ngay sau ô hiện tại.")

    def _update_size_info(self):
        """Cập nhật nhãn thông tin kích thước + thời gian ước tính (realtime)."""
        try:
            w = int(self.px_grid_w.get())
            h = int(self.px_grid_h.get())
            ox = int(self.px_offset_x.get())
            oy = int(self.px_offset_y.get())
        except Exception:
            return
        total = w * h
        secs = (total / 120.0) * 300 if total else 0
        if secs < 60:
            time_str = f"{secs:.0f} giây"
        elif secs < 3600:
            time_str = f"{secs/60:.1f} phút"
        else:
            time_str = f"{secs/3600:.1f} giờ"
        warn = ""
        if ox + w > 384 or oy + h > 240:
            warn = " ⚠ Vượt ngoài canvas! Giảm W/H hoặc giảm X/Y."
        self.px_size_info.set(
            f"Ảnh {w}×{h} = {total:,} ô · ước tính {time_str} (120 ô/5 phút)"
            f" · vẽ từ ({ox},{oy}) đến ({ox+w-1},{oy+h-1}).{warn}"
        )

    def _pixel_preview(self):
        """Hiển thị cửa sổ xem trước: ảnh gốc, ảnh pixel, và vị trí trên canvas."""
        from tkinter import Toplevel
        import pixel_painter as pp
        c = self._collect()
        if not c.pixel_image_path or not os.path.exists(c.pixel_image_path):
            messagebox.showwarning("Thiếu ảnh", "Chọn ảnh nguồn trước.")
            return
        try:
            palette = pp.build_palette(c)
            cells = pp.image_to_pixels(
                c.pixel_image_path, c.pixel_grid_w, c.pixel_grid_h, palette,
                dither=c.pixel_dither, bg_skip=c.pixel_bg_skip,
                offset_x=c.pixel_offset_x, offset_y=c.pixel_offset_y,
            )
        except Exception as e:
            messagebox.showerror("Lỗi", f"Không xử lý được ảnh: {e}")
            return

        win = Toplevel(self.root)
        win.title(f"👁 Xem trước — {c.pixel_grid_w}×{c.pixel_grid_h} = {len(cells)} ô")
        win.geometry("900x620")

        from PIL import Image, ImageDraw, ImageTk
        left = ttk.Frame(win)
        left.pack(side=LEFT, fill=BOTH, expand=True, padx=8, pady=8)
        ttk.Label(left, text="Ảnh gốc", font=("", 10, "bold")).pack(anchor=W)
        try:
            orig = Image.open(c.pixel_image_path).convert("RGB")
            orig.thumbnail((380, 260), Image.LANCZOS)
            self._prev_orig_img = ImageTk.PhotoImage(orig)
            ttk.Label(left, image=self._prev_orig_img).pack(anchor=W, pady=(0, 8))
        except Exception:
            pass
        ttk.Label(left, text=f"Ảnh pixel {c.pixel_grid_w}×{c.pixel_grid_h}", font=("", 10, "bold")).pack(anchor=W)
        pix_img = pp.render_preview(cells, c.pixel_grid_w, c.pixel_grid_h, cell_px=3)
        pix_img.thumbnail((380, 260), Image.NEAREST)
        self._prev_pix_img = ImageTk.PhotoImage(pix_img)
        ttk.Label(left, image=self._prev_pix_img).pack(anchor=W)

        right = ttk.Frame(win)
        right.pack(side=LEFT, fill=BOTH, expand=True, padx=8, pady=8)
        ox, oy = c.pixel_offset_x, c.pixel_offset_y
        w, h = c.pixel_grid_w, c.pixel_grid_h
        ttk.Label(right,
                  text=f"Vị trí trên canvas 384×240\nVẽ từ ({ox},{oy}) → ({ox+w-1},{oy+h-1})",
                  font=("", 10, "bold"), justify=LEFT).pack(anchor=W)
        canvas_img = Image.new("RGB", (384, 240), (255, 255, 255))
        draw = ImageDraw.Draw(canvas_img)
        for gx in range(0, 385, 32):
            draw.line([(gx, 0), (gx, 240)], fill=(235, 235, 235))
        for gy in range(0, 241, 32):
            draw.line([(0, gy), (384, gy)], fill=(235, 235, 235))
        thumb = pix_img.resize((max(1, w), max(1, h)), Image.NEAREST)
        canvas_img.paste(thumb, (ox, oy))
        draw.rectangle([ox, oy, ox + w - 1, oy + h - 1], outline=(239, 68, 68), width=2)
        canvas_img = canvas_img.resize((576, 360), Image.NEAREST)
        self._prev_canvas_img = ImageTk.PhotoImage(canvas_img)
        ttk.Label(right, image=self._prev_canvas_img).pack(anchor=W, pady=(4, 0))
        warn = ""
        if ox + w > 384 or oy + h > 240:
            warn = " ⚠ Vượt ngoài canvas — phần lố sẽ bị cắt!"
        ttk.Label(right,
                  text=f"{len(cells)} ô sẽ vẽ{warn}",
                  foreground="blue").pack(anchor=W, pady=(6, 0))
        ttk.Button(right, text="Đóng", command=win.destroy).pack(anchor=W, pady=(8, 0))

    def _pixel_run_selftest(self):
        """Chạy test độc lập: đăng nhập + vẽ 3 ô verify trên site thật."""
        c = self._collect()
        if not c.pixel_username or not c.pixel_password:
            messagebox.showwarning("Thiếu thông tin", "Nhập tài khoản/mật khẩu pixel trước.")
            return

        def run():
            import browser as br
            import dom_painter as dp
            import time as _t
            self._log("[Test] 🧪 Bắt đầu self-test DOM painter...")
            mgr = br.BrowserManager(c.session_dir, headless=False)
            mgr.start()
            try:
                page = mgr.new_page()
                ok = dp.login_and_open_canvas(page, c, self._log)
                if not ok:
                    self._log("[Test] ❌ Không vào được trang pixel.")
                    return
                ci = dp.get_canvas_info(page)
                if ci is None:
                    self._log("[Test] ❌ Không thấy canvas.")
                    return
                self._log(f"[Test] ✅ Canvas {ci.canvas_w}×{ci.canvas_h}, "
                          f"cell {ci.cell_px_x:.0f}×{ci.cell_px_y:.0f}px.")
                dp.reset_color_cache()
                tests = [
                    ((239, 68, 68), "đỏ", (50, 225)),
                    ((34, 197, 94), "xanh lá", (51, 225)),
                    ((59, 130, 246), "xanh dương", (52, 225)),
                ]
                allok = True
                for rgb, name, (gx, gy) in tests:
                    dp.set_color(page, rgb, self._log)
                    dp.paint_cell(page, ci, gx, gy)
                    _t.sleep(0.2)
                    ok = dp.verify_cell(page, gx, gy, rgb)
                    self._log(f"[Test] {'✅' if ok else '❌'} Ô ({gx},{gy}) {name}: {ok}")
                    allok = allok and ok
                if allok:
                    self._log("[Test] 🎉 SELF-TEST PASS — tool sẵn sàng vẽ thật!")
                else:
                    self._log("[Test] ❌ Có ô fail — kiểm tra log.")
                page.close()
            except Exception as e:
                self._log(f"[Test][Lỗi] {e}")
            finally:
                mgr.close()

        threading.Thread(target=run, daemon=True).start()

    def _pixel_test_one(self):
        """Vẽ đúng 1 ô đầu tiên để kiểm tra click có đúng vị trí/không."""
        c = self._collect()
        if not c.pixel_image_path or not os.path.exists(c.pixel_image_path):
            messagebox.showwarning("Thiếu ảnh", "Chọn ảnh nguồn trước.")
            return
        if not c.pixel_use_dom_mode and not (c.pixel_screen_canvas_x1 or c.pixel_screen_canvas_x2):
            messagebox.showwarning("Chưa canh", "Hãy 'Canh canvas' trước khi vẽ thử (screen mode).")
            return
        old_batch = c.pixel_batch_size
        c.pixel_batch_size = 1
        self._log("[Pixel] 🎯 Vẽ 1 ô thử — xem chuột có click đúng ô không.")
        self._pixel_paint_with_cfg(c, batch=True)
        c.pixel_batch_size = old_batch

    def _pixel_reset(self):
        c = self._collect()
        prog = c.pixel_progress_path or os.path.join(
            __import__("paths").app_dir(), "pixel_progress.json")
        if os.path.exists(prog):
            try:
                os.remove(prog)
                self._log(f"[Pixel] Đã xóa file tiến độ: {prog}")
            except OSError as e:
                self._log(f"[Pixel][Lỗi] không xóa được: {e}")
        self._set_pixel_progress(0.0, "Đã xóa tiến độ.")

    def _set_pixel_progress(self, pct: float, label: str):
        self.px_progress.set(pct)
        self.px_progress_label.set(label)

    # ---------------- Hành động ----------------
    def _collect(self) -> Config:
        c = self.cfg
        # Pixel Painter
        c.pixel_url = self.px_url.get().strip()
        c.pixel_grid_w = int(self.px_grid_w.get())
        c.pixel_grid_h = int(self.px_grid_h.get())
        c.pixel_offset_x = int(self.px_offset_x.get())
        c.pixel_offset_y = int(self.px_offset_y.get())
        c.pixel_cooldown_seconds = float(self.px_cooldown.get())
        c.pixel_jitter_seconds = float(self.px_jitter.get())
        c.pixel_palette_path = self.px_palette.get().strip()
        c.pixel_dither = bool(self.px_dither.get())
        c.pixel_bg_skip = bool(self.px_bg_skip.get())
        c.pixel_smart_skip = bool(self.px_smart_skip.get())
        c.pixel_color_tolerance = int(self.px_tolerance.get())
        c.pixel_batch_size = int(self.px_batch.get())
        c.pixel_image_path = self.px_image.get().strip()
        c.pixel_site_url = self.px_site_url.get().strip()
        c.pixel_username = self.px_username.get().strip()
        c.pixel_password = self.px_password.get().strip()
        c.pixel_wait_for_login = bool(self.px_wait_login.get())
        # Screen mode
        c.pixel_use_screen_mode = bool(self.px_screen_mode.get())
        c.pixel_use_dom_mode = bool(self.px_dom_mode.get())
        c.pixel_screen_canvas_x1 = int(self.px_cv_x1.get())
        c.pixel_screen_canvas_y1 = int(self.px_cv_y1.get())
        c.pixel_screen_canvas_x2 = int(self.px_cv_x2.get())
        c.pixel_screen_canvas_y2 = int(self.px_cv_y2.get())
        c.pixel_screen_palette_x1 = int(self.px_pl_x1.get())
        c.pixel_screen_palette_y1 = int(self.px_pl_y1.get())
        c.pixel_screen_palette_x2 = int(self.px_pl_x2.get())
        c.pixel_screen_palette_y2 = int(self.px_pl_y2.get())
        c.pixel_start_delay_seconds = float(self.px_start_delay.get())
        return c

    def _save(self):
        cfgmod.save(self._collect())
        self._log("Đã lưu cài đặt vào config.yaml.")

    def _on_close(self):
        """Tự lưu cấu hình khi đóng cửa sổ để mở lại không phải nhập lại.

        Tiến độ tô màu (pixel_progress.json) đã được lưu tự động sau mỗi ô,
        nên đóng app giữa chừng vẫn resume được.
        """
        try:
            self._save()
        except Exception:
            pass
        try:
            import screen_painter as sp
            sp.request_stop()
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

    # ---------------- Hotkey ESC toàn cục ----------------
    def _setup_global_hotkey(self):
        """Đăng ký ESC làm phím dừng khẩn (chạy nền, đọc message Windows)."""
        import ctypes
        import ctypes.wintypes as w

        MOD_NOREPEAT = 0x4000
        VK_ESCAPE = 0x1B
        HOTKEY_ID = 9001
        user32 = ctypes.windll.user32

        def worker():
            ok = user32.RegisterHotKey(None, HOTKEY_ID, MOD_NOREPEAT, VK_ESCAPE)
            if not ok:
                return
            msg = w.MSG()
            while True:
                if user32.GetMessageA(ctypes.byref(msg), None, 0, 0) > 0:
                    if msg.message == 0x0312:  # WM_HOTKEY
                        try:
                            import screen_painter as sp
                            sp.request_stop()
                            self._log("[Pixel] ⏹ ESC detected — đang dừng...")
                        except Exception:
                            pass
                else:
                    break
            user32.UnregisterHotKey(None, HOTKEY_ID)

        threading.Thread(target=worker, daemon=True).start()


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
