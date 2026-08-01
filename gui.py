"""Giao diện đồ họa (Tkinter) cho phần mềm auto check-in."""
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
        self.root.title("Auto Pixel Painter — DOM mode")
        self.root.geometry("760x780")
        self.root.minsize(720, 600)
        self.cfg = cfgmod.load()
        self.log_queue: queue.Queue[str] = queue.Queue()

        # Biến ràng buộc
        # Pixel Painter
        self.px_url = StringVar(value=self.cfg.pixel_url)
        self.px_grid_w = IntVar(value=self.cfg.pixel_grid_w)
        self.px_grid_h = IntVar(value=self.cfg.pixel_grid_h)
        self.px_offset_x = IntVar(value=getattr(self.cfg, "pixel_offset_x", 0))
        self.px_offset_y = IntVar(value=getattr(self.cfg, "pixel_offset_y", 0))
        self.px_cooldown = StringVar(value=str(self.cfg.pixel_cooldown_seconds))
        self.px_jitter = StringVar(value=str(self.cfg.pixel_jitter_seconds))
        self.px_dither = BooleanVar(value=self.cfg.pixel_dither)
        self.px_full_color = BooleanVar(value=getattr(self.cfg, "pixel_full_color", True))
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

        self._build_ui()
        self._poll_logs()
        self._setup_global_hotkey()

    # ---------------- UI ----------------
    def _build_ui(self):
        pad = {"padx": 8, "pady": 4}

        # Chỉ còn 1 nội dung: Pixel Art (DOM mode). Bỏ tab Cài đặt + Nhật ký.
        # Bọc trong canvas cuộn được (nội dung cao hơn cửa sổ).
        outer = ttk.Frame(self.root)
        outer.pack(fill=BOTH, expand=True, padx=8, pady=8)
        canvas = Canvas(outer, highlightthickness=0, borderwidth=0)
        vsb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=RIGHT, fill=Y)
        canvas.pack(side=LEFT, fill=BOTH, expand=True)
        tab = ttk.Frame(canvas)
        win_id = canvas.create_window((0, 0), window=tab, anchor="nw")

        # cuộn bằng lăn chuột
        def _on_wheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _on_wheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

        def _on_configure(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfigure(win_id, width=event.width)
        canvas.bind("<Configure>", _on_configure)
        # Lưu lại để widget đa tài khoản cập nhật scrollregion khi thêm/xóa dòng.
        self._pixel_tab = tab
        self._pixel_canvas = canvas

        self._build_pixel_content(tab)

        # Đã bỏ khung Nhật ký + dòng status "Sẵn sàng" theo yêu cầu.
        # Log giờ ghi ra console (stdout) để vẫn xem được khi chạy từ terminal.
        self.log_box = None
        self.status = StringVar(value="")

        # Nút điều khiển (giữ Lưu cài đặt).
        bar = ttk.Frame(self.root)
        bar.pack(fill=X, padx=8, pady=(0, 10))
        ttk.Button(bar, text="💾 Lưu cài đặt", command=self._save).pack(side=LEFT, padx=4)

    # ---------------- Pixel Art content ----------------
    def _build_pixel_content(self, tab: ttk.Frame):
        pad = {"padx": 8, "pady": 4}

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

        # Đăng nhập trang pixel (DOM mode) — gộp cả acc chính + danh sách N acc.
        lg = ttk.LabelFrame(
            tab, text="Đăng nhập trang (DOM mode) — tài khoản + đa tài khoản")
        lg.pack(fill=X, **pad)
        ttk.Label(lg, text="URL trang chính:").grid(row=0, column=0, sticky=W, padx=6, pady=4)
        ttk.Entry(lg, textvariable=self.px_site_url, width=40).grid(row=0, column=1, sticky=EW, padx=6, pady=4)
        ttk.Label(lg, text="Tài khoản:").grid(row=1, column=0, sticky=W, padx=6, pady=4)
        ttk.Entry(lg, textvariable=self.px_username, width=20).grid(row=1, column=1, sticky=W, padx=6, pady=4)
        ttk.Label(lg, text="Mật khẩu:").grid(row=2, column=0, sticky=W, padx=6, pady=4)
        ttk.Entry(lg, textvariable=self.px_password, width=20).grid(row=2, column=1, sticky=W, padx=6, pady=4)
        ttk.Checkbutton(lg, text="Chờ mình đăng nhập thủ công (dùng khi có captcha/2FA)",
                        variable=self.px_wait_login).grid(row=3, column=1, sticky=W, padx=6, pady=2)
        ttk.Label(lg, text="DOM mode: tool tự đăng nhập → bấm 'vẽ pixel' → vào trang canvas.",
                  foreground="gray").grid(row=4, column=1, sticky=W, padx=6)
        # ---- Đa tài khoản: danh sách dòng, mỗi dòng = Tài khoản + Mật khẩu + Xóa ----
        ttk.Separator(lg, orient=HORIZONTAL).grid(
            row=5, column=0, columnspan=4, sticky=EW, padx=6, pady=(8, 2))
        ttk.Label(
            lg,
            text="👥 Đa tài khoản — thêm các acc phụ để N acc cùng tô 1 bức (tự chia cột, "
                 "không đè nhau). Acc đầu tiên ở trên là acc chính.",
            foreground="gray", justify=LEFT,
        ).grid(row=6, column=0, columnspan=4, sticky=W, padx=6, pady=(2, 4))
        # Header cột.
        ttk.Label(lg, text="Tài khoản", font=("", 9, "bold")).grid(
            row=7, column=1, sticky=W, padx=6)
        ttk.Label(lg, text="Mật khẩu", font=("", 9, "bold")).grid(
            row=7, column=2, sticky=W, padx=6)
        # Container các dòng tài khoản.
        self._acc_rows_frame = ttk.Frame(lg)
        self._acc_rows_frame.grid(row=8, column=0, columnspan=4, sticky=EW, padx=6, pady=(0, 4))
        self._acc_rows_frame.columnconfigure(1, weight=1)
        self._acc_rows_frame.columnconfigure(2, weight=1)
        self.px_acc_rows: list[dict] = []  # list[{"user": StringVar, "pass": StringVar}]
        # Nút thêm acc.
        ttk.Button(lg, text="➕ Thêm tài khoản",
                   command=self._add_acc_row).grid(row=9, column=0, columnspan=4,
                                                    sticky=W, padx=6, pady=(0, 6))
        ttk.Label(
            lg,
            text="→ Tool chia đều cột ảnh cho từng acc, mỗi acc mở Chrome + session + tiến độ "
                 "RIÊNG. Acc bị rate-limit chỉ acc đó đợi, các acc khác vẫn tô.",
            foreground="gray", justify=LEFT,
        ).grid(row=10, column=0, columnspan=4, sticky=W, padx=6, pady=(2, 6))
        lg.columnconfigure(1, weight=1)
        lg.columnconfigure(2, weight=1)
        # Khởi tạo các dòng từ config (acc chính + acc phụ trong pixel_multi_accounts).
        self._init_acc_rows()

        # URL trang pixel
        cv = ttk.LabelFrame(tab, text="URL trang pixel")
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
        gr = ttk.LabelFrame(tab, text="📏 Kích thước ảnh pixel & vị trí vẽ (canvas thật 512×320)")
        gr.pack(fill=X, **pad)
        ttk.Label(gr, text="Rộng ảnh (ô):").grid(row=0, column=0, sticky=W, padx=6, pady=4)
        ttk.Spinbox(gr, from_=2, to=512, textvariable=self.px_grid_w, width=8).grid(row=0, column=1, sticky=W, padx=6)
        ttk.Label(gr, text="Cao ảnh (ô):").grid(row=0, column=2, sticky=W, padx=6, pady=4)
        ttk.Spinbox(gr, from_=2, to=320, textvariable=self.px_grid_h, width=8).grid(row=0, column=3, sticky=W, padx=6)
        ttk.Label(gr, text="→ Vẽ từ ô X:").grid(row=1, column=0, sticky=W, padx=6, pady=4)
        ttk.Spinbox(gr, from_=0, to=511, textvariable=self.px_offset_x, width=8).grid(row=1, column=1, sticky=W, padx=6)
        ttk.Label(gr, text="Y:").grid(row=1, column=2, sticky=W, padx=6, pady=4)
        ttk.Spinbox(gr, from_=0, to=319, textvariable=self.px_offset_y, width=8).grid(row=1, column=3, sticky=W, padx=6)
        ttk.Label(gr, text="Cooldown (giây):").grid(row=2, column=0, sticky=W, padx=6, pady=4)
        ttk.Entry(gr, textvariable=self.px_cooldown, width=8).grid(row=2, column=1, sticky=W, padx=6)
        ttk.Label(gr, text="Nhiễu ± (giây):").grid(row=2, column=2, sticky=W, padx=6, pady=4)
        ttk.Entry(gr, textvariable=self.px_jitter, width=8).grid(row=2, column=3, sticky=W, padx=6)
        ttk.Label(gr, text="Vẽ từng mẻ (số ô):").grid(row=3, column=0, sticky=W, padx=6, pady=4)
        ttk.Spinbox(gr, from_=0, to=100000, textvariable=self.px_batch, width=8).grid(row=3, column=1, sticky=W, padx=6)
        ttk.Label(gr, text="0 = vẽ hết", foreground="gray").grid(row=3, column=2, columnspan=2, sticky=W, padx=6)
        # Hiển thị động tổng số ô + thời gian ước tính.
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
        ttk.Checkbutton(opt, text="🎨 Toàn màu (giữ màu gốc, chi tiết nhất — chỉ DOM mode)",
                        variable=self.px_full_color).grid(row=2, column=0, columnspan=2, sticky=W, padx=6, pady=4)
        ttk.Label(opt, text="🖼 Độ mờ ảnh overlay:").grid(row=3, column=0, sticky=W, padx=6, pady=4)
        self.px_overlay = DoubleVar(value=getattr(self.cfg, "pixel_overlay_opacity", 0.35))
        ttk.Spinbox(opt, from_=0, to=1, increment=0.05, textvariable=self.px_overlay,
                    width=6, format="%.2f").grid(row=3, column=1, sticky=W, padx=(20, 0), pady=4)
        ttk.Label(opt, text="(0=tắt, 0.35=vừa)", foreground="gray").grid(
            row=3, column=1, sticky=E, padx=70, pady=4)

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
        ttk.Button(row, text="💾 Lưu ảnh pixel", command=self._pixel_save_png).pack(side=LEFT, padx=4)
        ttk.Button(row, text="🔍 Dò lại & tô", command=self._pixel_repaint_diff).pack(side=LEFT, padx=4)
        ttk.Button(row, text="🎯 Vẽ 1 ô thử", command=self._pixel_test_one).pack(side=LEFT, padx=4)
        ttk.Button(row, text="▶ Vẽ thử (mẻ)", command=self._pixel_paint_batch).pack(side=LEFT, padx=4)
        ttk.Button(row, text="▶ Vẽ tất cả", command=self._pixel_paint_all).pack(side=LEFT, padx=4)
        ttk.Button(row, text="👥 Vẽ đa tài khoản", command=self._pixel_paint_multi).pack(side=LEFT, padx=4)
        ttk.Button(row, text="⏹ Hủy (ESC)", command=self._pixel_cancel).pack(side=LEFT, padx=4)
        ttk.Button(row, text="🔄 Xóa tiến độ", command=self._pixel_reset).pack(side=LEFT, padx=4)

        # Hàng 2: Lưu/Mở dự án (đóng gói setup + ảnh + tiến độ để mở lại chạy tiếp).
        row2 = ttk.Frame(tab)
        row2.pack(fill=X, padx=4, pady=2)
        ttk.Button(row2, text="💾 Lưu dự án", command=self._project_save).pack(side=LEFT, padx=4)
        ttk.Button(row2, text="📂 Mở dự án", command=self._project_load).pack(side=LEFT, padx=4)
        ttk.Label(row2, text="(lưu setup + ảnh pixel + tiến độ để mở lại chạy tiếp)",
                  foreground="gray").pack(side=LEFT, padx=4)

        self._pixel_cancel_flag = False
        # Hiện thông tin kích thước ngay khi mở.
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

    # ---------------- Đa tài khoản: danh sách dòng thêm/xóa ----------------
    def _init_acc_rows(self):
        """Khởi tạo các dòng tài khoản từ config.

        Dòng đầu luôn hiển thị acc chính (pixel_username/pixel_password) — không xóa được.
        Các dòng tiếp theo parse từ pixel_multi_accounts (chuỗi 'user|pass;...').
        """
        # Dòng 1: acc chính (chỉ hiển thị, không có nút xóa).
        self._add_acc_row(
            user=self.cfg.pixel_username,
            password=self.cfg.pixel_password,
            removable=False,
        )
        # Các acc phụ.
        raw = (self.cfg.pixel_multi_accounts or "").strip()
        if raw:
            for part in raw.split(";"):
                part = part.strip()
                if not part:
                    continue
                if "|" in part:
                    u, p = part.split("|", 1)
                elif ":" in part:
                    u, p = part.split(":", 1)
                else:
                    u, p = part, ""
                u, p = u.strip(), p.strip()
                if u:
                    self._add_acc_row(user=u, password=p, removable=True)

    def _add_acc_row(self, user: str = "", password: str = "", removable: bool = True):
        """Thêm 1 dòng tài khoản vào danh sách."""
        idx = len(self.px_acc_rows)
        row_frame = ttk.Frame(self._acc_rows_frame)
        row_frame.grid(row=idx, column=0, columnspan=4, sticky=EW, pady=1)
        row_frame.columnconfigure(1, weight=1)
        row_frame.columnconfigure(2, weight=1)
        # Số thứ tự.
        ttk.Label(row_frame, text=f"{idx + 1}.", width=3).grid(row=0, column=0, sticky=W, padx=(0, 4))
        u_var = StringVar(value=user)
        p_var = StringVar(value=password)
        ttk.Entry(row_frame, textvariable=u_var, width=22).grid(row=0, column=1, sticky=EW, padx=2)
        ttk.Entry(row_frame, textvariable=p_var, width=22).grid(row=0, column=2, sticky=EW, padx=2)
        if removable:
            def _remove(_r=row_frame, _vars=(u_var, p_var)):
                self._remove_acc_row(_r, _vars)
            ttk.Button(row_frame, text="✕", width=3, command=_remove).grid(
                row=0, column=3, sticky=W, padx=2)
        self.px_acc_rows.append({"user": u_var, "pass": p_var, "frame": row_frame, "removable": removable})
        self._refresh_acc_scroll()

    def _remove_acc_row(self, row_frame, vars_tuple):
        """Xóa 1 dòng tài khoản (chỉ dòng có nút ✕)."""
        u_var, p_var = vars_tuple
        # Tìm và xóa khỏi list.
        for i, r in enumerate(self.px_acc_rows):
            if r["user"] is u_var and r["pass"] is p_var:
                if not r.get("removable", False):
                    return  # không xóa dòng acc chính
                r["frame"].destroy()
                del self.px_acc_rows[i]
                break
        # Đánh số lại + dồn lên.
        self._relayout_acc_rows()
        self._refresh_acc_scroll()

    def _relayout_acc_rows(self):
        """Đánh số thứ tự lại và dời các dòng lên sau khi xóa."""
        for i, r in enumerate(self.px_acc_rows):
            r["frame"].grid(row=i, column=0, columnspan=4, sticky=EW, pady=1)
            # Cập nhật label số thứ tự (con đầu tiên trong frame).
            for child in r["frame"].winfo_children():
                if isinstance(child, ttk.Label) and child.cget("text").rstrip(".").isdigit():
                    child.config(text=f"{i + 1}.")
                    break

    def _refresh_acc_scroll(self):
        """Cập nhật scrollregion của canvas pixel tab sau khi thêm/xóa dòng."""
        try:
            self.root.update_idletasks()
            self._pixel_canvas.configure(scrollregion=self._pixel_canvas.bbox("all"))
        except Exception:
            pass

    def _collect_accounts(self) -> list[tuple[str, str]]:
        """Thu thập danh sách (user, pass) từ các dòng, bỏ dòng trống."""
        accounts: list[tuple[str, str]] = []
        for r in self.px_acc_rows:
            u = r["user"].get().strip()
            p = r["pass"].get().strip()
            if u:
                accounts.append((u, p))
        return accounts

    def _pixel_preview(self):
        c = self._collect()
        if not c.pixel_image_path or not os.path.exists(c.pixel_image_path):
            messagebox.showwarning("Thiếu ảnh", "Hãy chọn ảnh nguồn trước.")
            return
        try:
            import pixel_painter as pp
            out = pp.generate_preview(c)
            self._log(f"🖼 Đã tạo preview: {out}")
            try:
                os.startfile(out)  # type: ignore[attr-defined]
            except Exception:
                pass
        except Exception as e:
            messagebox.showerror("Lỗi preview", str(e))

    def _pixel_save_png(self):
        """Lưu ảnh pixel (preview) ra file PNG do user chọn."""
        c = self._collect()
        if not c.pixel_image_path or not os.path.exists(c.pixel_image_path):
            messagebox.showwarning("Thiếu ảnh", "Hãy chọn ảnh nguồn trước.")
            return
        # Hỏi nơi lưu.
        try:
            from tkinter import filedialog
        except Exception:
            import tkinter.filedialog as filedialog  # type: ignore
        init = "pixel_saved.png"
        out = filedialog.asksaveasfilename(
            title="Lưu ảnh pixel ra đâu?",
            defaultextension=".png",
            filetypes=[("PNG", "*.png")],
            initialfile=init,
        )
        if not out:
            return
        try:
            import pixel_painter as pp
            saved = pp.generate_preview(c, out_path=out)
            self._log(f"💾 Đã lưu ảnh pixel: {saved}")
            try:
                os.startfile(saved)  # type: ignore[attr-defined]
            except Exception:
                pass
        except Exception as e:
            messagebox.showerror("Lỗi lưu ảnh", str(e))

    def _pixel_repaint_diff(self):
        """Dò lại ô sai màu rồi tô.

        Mở hộp thoại chọn ảnh PNG (ảnh pixel đã lưu hoặc bất kỳ ảnh nào),
        set tạm làm ảnh nguồn, bật Smart skip (chỉ tô ô sai màu), rồi vẽ.
        Smart skip sẽ đọc canvas thật, so sánh từng ô với ảnh -> chỉ tô ô lệch màu.
        """
        c = self._collect()
        if not c.pixel_site_url:
            messagebox.showwarning(
                "Thiếu URL", "Nhập 'URL trang chính' (DOM mode) trước.")
            return
        # Chọn ảnh để dò lại (mặc định gợi ý file đã lưu).
        try:
            from tkinter import filedialog
        except Exception:
            import tkinter.filedialog as filedialog  # type: ignore
        img = filedialog.askopenfilename(
            title="Chọn ảnh để dò lại (ảnh pixel đã lưu hoặc ảnh nguồn)",
            filetypes=[("Ảnh", "*.png *.jpg *.jpeg *.bmp"), ("All", "*.*")],
        )
        if not img:
            return
        # Set ảnh tạm + bật smart skip để chỉ tô ô sai.
        c.pixel_image_path = img
        c.pixel_smart_skip = True
        c.pixel_use_dom_mode = True
        # Dò lại không cần quan tâm batch -> vẽ hết các ô sai.
        self._log(f"🔍 Dò lại ô sai màu từ ảnh: {img} (Smart skip đã bật).")
        self._pixel_paint_with_cfg(c, batch=False)

    def _pixel_paint_batch(self):
        self._pixel_paint(batch=True)

    def _pixel_paint_all(self):
        self._pixel_paint(batch=False)

    def _pixel_paint_multi(self):
        """Vẽ bằng N tài khoản song song — mỗi acc tô 1 dải cột, không đè nhau."""
        c = self._collect()
        if not c.pixel_image_path or not os.path.exists(c.pixel_image_path):
            messagebox.showwarning("Thiếu ảnh", "Chọn ảnh nguồn trước.")
            return
        if not c.pixel_site_url:
            messagebox.showwarning("Thiếu URL", "Nhập 'URL trang chính' (DOM mode) trước.")
            return
        # Lấy danh sách tài khoản từ các dòng đã nhập.
        accounts = self._collect_accounts()
        if not accounts:
            messagebox.showwarning(
                "Thiếu tài khoản",
                "Nhập ít nhất 1 tài khoản ở ô 'Tài khoản' trên.",
            )
            return
        n = len(accounts)
        ok = messagebox.askyesno(
            "Xác nhận đa tài khoản",
            f"Sẽ mở {n} Chrome song song, mỗi acc tô 1/{n} bức tranh.\n\n"
            f"Số acc: {n}\n"
            + "\n".join(f"  • {u}" for u, _ in accounts) +
            "\n\nMỗi acc có rate-limit riêng (600 ô/5 phút). Tiếp tục?"
        )
        if not ok:
            return
        # Bật DOM mode cho multi-account.
        c.pixel_use_dom_mode = True
        # Dòng đầu -> acc chính; các dòng còn lại -> acc phụ.
        c.pixel_username, c.pixel_password = accounts[0]
        c.pixel_multi_accounts = ";".join(
            f"{u}|{p}" for u, p in accounts[1:]) if len(accounts) > 1 else ""
        try:
            import screen_painter as sp
            sp.clear_stop()
        except Exception:
            pass
        self._pixel_cancel_flag = False
        self._log(f"[Multi] 🚀 Bắt đầu vẽ đa tài khoản ({n} acc song song)...")

        # State tiến độ từng acc (parse từ log worker): {acc_idx: (done, total)}.
        import re as _re
        self._multi_progress: dict[int, tuple[int, int]] = {}

        # Regex parse log worker:
        #   "[A1/3] [DOM] Đã tô 10 ô (20/5913)."
        #   "[A2/3] ✅ Xong: đã tô 5913 ô đợt này · Tổng 5913/5913."
        _pat_done = _re.compile(r"\[A(\d+)/\d+\].*?\((\d+)/(\d+)\)\s*\.")
        _pat_total = _re.compile(r"\[A(\d+)/\d+\].*?Tổng\s+(\d+)/(\d+)")

        def multi_log(msg: str):
            """Log thường + parse tiến độ để cập nhật thanh tổng."""
            self._log(msg)
            # Thử parse 2 dạng log.
            for pat in (_pat_done, _pat_total):
                m = pat.search(msg)
                if m:
                    acc_idx = int(m.group(1)) - 1
                    done = int(m.group(2))
                    tot = int(m.group(3))
                    self._multi_progress[acc_idx] = (done, tot)
            # Tính tổng nếu có dữ liệu.
            if self._multi_progress:
                tot_done = sum(d for d, _ in self._multi_progress.values())
                tot_all = sum(t for _, t in self._multi_progress.values())
                if tot_all > 0:
                    pct = tot_done / tot_all * 100.0
                    # Mô tả chi tiết từng acc.
                    parts = []
                    for ai in range(n):
                        if ai in self._multi_progress:
                            d, t = self._multi_progress[ai]
                            parts.append(f"A{ai+1}:{d}/{t}")
                    desc = f"Đa TK tổng {tot_done}/{tot_all} ô ({pct:.1f}%) | " + " ".join(parts)
                    self._set_pixel_progress(pct, desc)

        def on_progress(acc_idx: int, done: int, tot: int):
            # Callback này không được worker gọi (worker là subprocess), nhưng giữ
            # để tương thích. Tiến độ thật parse từ log qua multi_log.
            self._multi_progress[acc_idx] = (done, tot)

        def run():
            try:
                import multi_account as ma
                ma.run_multi_account(c, log=multi_log, on_progress=on_progress)
            except Exception as e:
                multi_log(f"[Multi][Lỗi] {e}")

        threading.Thread(target=run, daemon=True).start()

    def _pixel_paint(self, batch: bool):
        c = self._collect()
        if not c.pixel_image_path or not os.path.exists(c.pixel_image_path):
            messagebox.showwarning("Thiếu ảnh", "Chọn ảnh nguồn trước.")
            return
        if not c.pixel_site_url:
            messagebox.showwarning("Thiếu URL", "Nhập 'URL trang chính' (DOM mode) trước.")
            return
        self._pixel_paint_with_cfg(c, batch)

    def _pixel_paint_with_cfg(self, c: Config, batch: bool):
        """Khởi chạy thread vẽ với config đã thu thập (luôn DOM mode)."""
        try:
            import screen_painter as sp
            sp.clear_stop()
        except Exception:
            pass
        self._pixel_cancel_flag = False
        if batch and c.pixel_batch_size <= 0:
            c.pixel_batch_size = 50  # mặc định vẽ thử 50 ô

        c.pixel_use_dom_mode = True
        c.pixel_use_screen_mode = False
        threading.Thread(target=self._paint_dom, args=(c, batch), daemon=True).start()

    def _paint_dom(self, c: Config, batch: bool):
        """DOM mode — Playwright mở Chrome, click element DOM. Không cần giữ focus."""
        try:
            import dom_painter as dp
            import pixel_painter as pp
            import browser as br
            palette = pp.build_palette(c)
            plan = pp.PixelPlan.load(c.pixel_progress_path, c)
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
                # Đăng nhập trang chính rồi bấm 'vẽ pixel' để vào trang canvas.
                # Hàm này tự chờ người dùng nếu tự động fail (KHÔNG tắt Chrome vội).
                ok = dp.login_and_open_canvas(page, c, self._log)
                if not ok:
                    self._log("[DOM] Không vào được trang canvas sau khi chờ. "
                              "Chrome vẫn mở — bạn có thể tự xử lý rồi chạy lại. "
                              "Nhấn ESC trên app để đóng.")
                    # Giữ Chrome mở thêm cho người dùng xem, chờ ESC.
                    import screen_painter as sp
                    import time as _t
                    while not sp.is_stopped():
                        _t.sleep(1)
                    return
                # Lấy thông tin canvas HTML5.
                ci = dp.get_canvas_info(page)
                if ci is None:
                    self._log("[DOM][Lỗi] Không thấy canvas. Chưa vào trang pixel?")
                    return
                self._log(f"[DOM] Canvas: {ci.canvas_w}×{ci.canvas_h}, "
                          f"ô {ci.cell_px_x:.0f}×{ci.cell_px_y:.0f}px.")
                page_palette = dp.read_palette(page)
                self._log(f"[DOM] Palette: {len(page_palette)} màu.")

                # Phủ ảnh gốc lên canvas (overlay) để xem ảnh tham chiếu khi vẽ.
                dp.show_image_overlay(page, ci, c, self._log)

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
                dp.hide_image_overlay(page)
                self._log("[DOM] Xong. Đang đóng Chrome...")
                page.close()
            finally:
                mgr.close()
        except Exception as e:
            import traceback
            self._log(f"[DOM][Lỗi] {e}")
            self._log(traceback.format_exc())
            self._log("⏸ Chrome vẫn mở để bạn xem lỗi. Nhấn ESC trên GUI để đóng.")

    # ---------------- Canh vị trí (calibration) — kéo-thả chọn vùng ----------
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
        # Tốc độ: dùng cfg.pixel_rate_limit (mặc định 600) / cfg.pixel_rate_window (300s).
        # Trước đây hardcode 120 -> ước tính sai (Ảnh 100×80 báo 5.6 giờ thay vì 1.1 giờ).
        rate_limit = getattr(self.cfg, "pixel_rate_limit", 600) or 600
        rate_window = getattr(self.cfg, "pixel_rate_window", 300) or 300
        # Nếu bật humanize (vẽ theo nét + nghỉ), tốc độ thực chậm hơn ~3-4 lần.
        # Ước tính trung bình ~1.5s/ô (so với 0.5s/ô khi vẽ nhanh).
        humanize = getattr(self.cfg, "pixel_humanize", True)
        secs_per_cell = (rate_window / rate_limit) * (3.0 if humanize else 1.0)
        secs = total * secs_per_cell if total else 0
        if secs < 60:
            time_str = f"{secs:.0f} giây"
        elif secs < 3600:
            time_str = f"{secs/60:.1f} phút"
        else:
            time_str = f"{secs/3600:.1f} giờ"
        # Cảnh báo vượt canvas thật (site datn: 512×320, không phải 384×240 cũ).
        canvas_gw = 512  # grid thật site datn (canvas 2048×1280, cell 4px)
        canvas_gh = 320
        warn = ""
        if ox + w > canvas_gw or oy + h > canvas_gh:
            warn = (f" ⚠ Vượt ngoài canvas ({canvas_gw}×{canvas_gh})! "
                    f"Giảm W/H hoặc giảm X/Y.")
        mode_tag = "humanize ~1.5s/ô" if humanize else f"{rate_limit} ô/{rate_window}s"
        self.px_size_info.set(
            f"Ảnh {w}×{h} = {total:,} ô · ước tính {time_str} ({mode_tag})"
            f" · vẽ từ ({ox},{oy}) đến ({ox+w-1},{oy+h-1}).{warn}"
        )

    def _pixel_preview(self):
        """Hiển thị cửa sổ xem trước: ảnh gốc, ảnh pixel, và vị trí trên canvas."""
        import io
        import math
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
        # Panel trái: ảnh gốc + ảnh pixel (side by side).
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
        # Ảnh pixel (tô cell thật, NEAREST để thấy rõ ô).
        pix_img = pp.render_preview(cells, c.pixel_grid_w, c.pixel_grid_h, cell_px=3)
        pix_img.thumbnail((380, 260), Image.NEAREST)
        self._prev_pix_img = ImageTk.PhotoImage(pix_img)
        ttk.Label(left, image=self._prev_pix_img).pack(anchor=W)

        # Panel phải: canvas 512×320 (grid thật site datn) với ảnh đặt đúng vị trí offset.
        right = ttk.Frame(win)
        right.pack(side=LEFT, fill=BOTH, expand=True, padx=8, pady=8)
        ox, oy = c.pixel_offset_x, c.pixel_offset_y
        w, h = c.pixel_grid_w, c.pixel_grid_h
        ttk.Label(right,
                  text=f"Vị trí trên canvas 512×320\nVẽ từ ({ox},{oy}) → ({ox+w-1},{oy+h-1})",
                  font=("", 10, "bold"), justify=LEFT).pack(anchor=W)
        # Vẽ canvas trắng, đặt khung đỏ đánh dấu vùng ảnh.
        canvas_img = Image.new("RGB", (512, 320), (255, 255, 255))
        draw = ImageDraw.Draw(canvas_img)
        # Lưới mờ mỗi 32 ô cho dễ định vị.
        for gx in range(0, 513, 32):
            draw.line([(gx, 0), (gx, 320)], fill=(235, 235, 235))
        for gy in range(0, 321, 32):
            draw.line([(0, gy), (512, gy)], fill=(235, 235, 235))
        # Tô thumbnail ảnh pixel vào đúng vị trí (scale xuống).
        thumb = pix_img.resize((max(1, w), max(1, h)), Image.NEAREST)
        canvas_img.paste(thumb, (ox, oy))
        # Khung đỏ quanh vùng ảnh.
        draw.rectangle([ox, oy, ox + w - 1, oy + h - 1], outline=(239, 68, 68), width=2)
        canvas_img = canvas_img.resize((576, 360), Image.NEAREST)
        self._prev_canvas_img = ImageTk.PhotoImage(canvas_img)
        ttk.Label(right, image=self._prev_canvas_img).pack(anchor=W, pady=(4, 0))
        warn = ""
        if ox + w > 512 or oy + h > 320:
            warn = " ⚠ Vượt ngoài canvas (512×320) — phần lố sẽ bị cắt!"
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
        old_batch = c.pixel_batch_size
        c.pixel_batch_size = 1
        self._log("[Pixel] 🎯 Vẽ 1 ô thử — xem chuột có click đúng ô không.")
        self._pixel_paint_with_cfg(c, batch=True)
        c.pixel_batch_size = old_batch

    def _pixel_reset(self):
        c = self._collect()
        try:
            from config import app_dir
        except Exception:
            app_dir = lambda: os.path.dirname(os.path.abspath(__file__))  # type: ignore
        prog = c.pixel_progress_path or os.path.join(app_dir(), "pixel_progress.json")
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

    # ---------------- Lưu / Mở dự án (setup + ảnh + tiến độ) ----------------
    def _project_signature(self) -> dict:
        """Tạo 'chữ ký' của setup hiện tại để khớp khi resume (tránh tô lại)."""
        c = self._collect()
        return {
            "image_path": os.path.abspath(c.pixel_image_path) if c.pixel_image_path else "",
            "grid_w": c.pixel_grid_w,
            "grid_h": c.pixel_grid_h,
            "offset_x": c.pixel_offset_x,
            "offset_y": c.pixel_offset_y,
            "dither": bool(c.pixel_dither),
            "bg_skip": bool(c.pixel_bg_skip),
            "full_color": bool(getattr(c, "pixel_full_color", False)),
            "palette_path": c.pixel_palette_path or "",
        }

    def _project_save(self):
        """Lưu toàn bộ setup + ảnh đã pixel + tiến độ vào 1 file .pixproj.

        File chứa: setup (grid, offset, tài khoản, URL...), đường dẫn ảnh nguồn,
        và COPY toàn bộ pixel_progress_acc*.json. Mở lại -> khôi phục GUI +
        khôi phục tiến độ -> bấm chạy là tô tiếp (không tạo lại ảnh).
        """
        c = self._collect()
        if not c.pixel_image_path or not os.path.exists(c.pixel_image_path):
            messagebox.showwarning("Thiếu ảnh", "Chọn ảnh nguồn trước khi lưu dự án.")
            return
        try:
            from config import app_dir
        except Exception:
            app_dir = lambda: os.path.dirname(os.path.abspath(__file__))  # type: ignore
        default_name = os.path.splitext(os.path.basename(c.pixel_image_path))[0] + ".pixproj"
        path = filedialog.asksaveasfilename(
            title="Lưu dự án pixel",
            defaultextension=".pixproj",
            initialfile=default_name,
            filetypes=[("Pixel project", "*.pixproj"), ("All files", "*.*")],
        )
        if not path:
            return
        import json
        # Thu thập progress files của multi-account + single.
        progress = {}
        base = app_dir()
        for fn in os.listdir(base):
            if fn.startswith("pixel_progress") and fn.endswith(".json"):
                fp = os.path.join(base, fn)
                try:
                    with open(fp, "r", encoding="utf-8") as f:
                        progress[fn] = json.load(f)
                except Exception:
                    pass
        accounts = self._collect_accounts()
        project = {
            "version": 1,
            "signature": self._project_signature(),
            "setup": {
                "pixel_url": c.pixel_url,
                "pixel_site_url": c.pixel_site_url,
                "pixel_image_path": c.pixel_image_path,
                "pixel_grid_w": c.pixel_grid_w,
                "pixel_grid_h": c.pixel_grid_h,
                "pixel_offset_x": c.pixel_offset_x,
                "pixel_offset_y": c.pixel_offset_y,
                "pixel_cooldown_seconds": c.pixel_cooldown_seconds,
                "pixel_jitter_seconds": c.pixel_jitter_seconds,
                "pixel_overlay_opacity": getattr(c, "pixel_overlay_opacity", 0.35),
                "pixel_dither": bool(c.pixel_dither),
                "pixel_full_color": bool(getattr(c, "pixel_full_color", False)),
                "pixel_bg_skip": bool(c.pixel_bg_skip),
                "pixel_smart_skip": bool(c.pixel_smart_skip),
                "pixel_color_tolerance": c.pixel_color_tolerance,
                "pixel_batch_size": c.pixel_batch_size,
                "pixel_wait_for_login": bool(c.pixel_wait_for_login),
                "accounts": [{"user": u, "pass": p} for u, p in accounts],
            },
            "progress": progress,
            "saved_at": os.path.getmtime(c.pixel_image_path) if os.path.exists(c.pixel_image_path) else 0,
        }
        try:
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(project, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
            n = len(progress)
            total_done = sum(p.get("index", 0) for p in progress.values())
            total_all = sum(len(p.get("cells", [])) for p in progress.values())
            self._log(f"💾 Đã lưu dự án: {path}")
            self._log(f"    • {n} file tiến độ · đã tô {total_done}/{total_all} ô.")
            messagebox.showinfo("Lưu dự án", f"Đã lưu:\n{path}\n\nTiến độ: {total_done}/{total_all} ô.")
        except Exception as e:
            messagebox.showerror("Lỗi lưu", str(e))

    def _project_load(self):
        """Mở file .pixproj -> khôi phục GUI + tiến độ -> chạy tiếp được ngay."""
        path = filedialog.askopenfilename(
            title="Mở dự án pixel",
            filetypes=[("Pixel project", "*.pixproj"), ("All files", "*.*")],
        )
        if not path:
            return
        import json
        try:
            with open(path, "r", encoding="utf-8") as f:
                project = json.load(f)
        except Exception as e:
            messagebox.showerror("Lỗi mở", f"Không đọc được file dự án:\n{e}")
            return
        setup = project.get("setup", {})
        img = setup.get("pixel_image_path", "")
        if img and not os.path.exists(img):
            self._log(f"⚠️ Ảnh nguồn không còn ở đường dẫn cũ: {img}")
            self._log("   Hãy chọn lại ảnh thủ công sau khi load.")
        # Khôi phục GUI fields.
        try:
            if img:
                self.px_image.set(img)
            self.px_url.set(setup.get("pixel_url", ""))
            self.px_site_url.set(setup.get("pixel_site_url", ""))
            self.px_grid_w.set(int(setup.get("pixel_grid_w", 512)))
            self.px_grid_h.set(int(setup.get("pixel_grid_h", 320)))
            self.px_offset_x.set(int(setup.get("pixel_offset_x", 0)))
            self.px_offset_y.set(int(setup.get("pixel_offset_y", 0)))
            self.px_cooldown.set(str(setup.get("pixel_cooldown_seconds", 0.5)))
            self.px_jitter.set(str(setup.get("pixel_jitter_seconds", 0.2)))
            self.px_dither.set(bool(setup.get("pixel_dither", False)))
            self.px_full_color.set(bool(setup.get("pixel_full_color", False)))
            self.px_bg_skip.set(bool(setup.get("pixel_bg_skip", False)))
            self.px_smart_skip.set(bool(setup.get("pixel_smart_skip", True)))
            self.px_tolerance.set(int(setup.get("pixel_color_tolerance", 24)))
            self.px_batch.set(int(setup.get("pixel_batch_size", 0)))
            self.px_wait_login.set(bool(setup.get("pixel_wait_for_login", False)))
        except Exception as e:
            self._log(f"⚠️ Lỗi khôi phục GUI: {e}")
        # Khôi phục danh sách tài khoản.
        accounts = setup.get("accounts", [])
        if accounts:
            # Xóa các dòng phụ (giữ dòng acc chính đầu tiên).
            for r in list(self.px_acc_rows):
                if r.get("removable", False):
                    try:
                        r["frame"].destroy()
                    except Exception:
                        pass
            self.px_acc_rows = [r for r in self.px_acc_rows if not r.get("removable", False)]
            # Điền acc chính.
            if self.px_acc_rows:
                self.px_acc_rows[0]["user"].set(accounts[0].get("user", ""))
                self.px_acc_rows[0]["pass"].set(accounts[0].get("pass", ""))
            # Thêm acc phụ.
            for acc in accounts[1:]:
                self._add_acc_row(
                    user=acc.get("user", ""), password=acc.get("pass", ""), removable=True
                )
            self._refresh_acc_scroll()
        # Khôi phục progress files.
        try:
            from config import app_dir
        except Exception:
            app_dir = lambda: os.path.dirname(os.path.abspath(__file__))  # type: ignore
        progress = project.get("progress", {})
        base = app_dir()
        restored = 0
        for fn, data in progress.items():
            fp = os.path.join(base, fn)
            try:
                tmp = fp + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(data, f)
                os.replace(tmp, fp)
                restored += 1
            except Exception as e:
                self._log(f"⚠️ Không khôi phục được {fn}: {e}")
        # Báo cáo.
        total_done = sum(p.get("index", 0) for p in progress.values())
        total_all = sum(len(p.get("cells", [])) for p in progress.values())
        self._log(f"📂 Đã mở dự án: {path}")
        self._log(f"    • Khôi phục {restored}/{len(progress)} file tiến độ.")
        self._log(f"    • Tiến độ: {total_done}/{total_all} ô đã tô.")
        if total_all > 0:
            pct = total_done / total_all * 100.0
            self._set_pixel_progress(pct, f"Tiếp tục: {total_done}/{total_all} ô ({pct:.1f}%)")
        try:
            self._update_size_info()
        except Exception:
            pass
        messagebox.showinfo(
            "Mở dự án",
            f"Đã khôi phục setup + tiến độ.\n\n"
            f"Đã tô: {total_done}/{total_all} ô.\n\n"
            f"Bấm '👥 Vẽ đa tài khoản' để tô tiếp.",
        )

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
        try:
            c.pixel_overlay_opacity = float(self.px_overlay.get())
        except Exception:
            c.pixel_overlay_opacity = 0.35
        c.pixel_dither = bool(self.px_dither.get())
        c.pixel_full_color = bool(self.px_full_color.get())
        c.pixel_bg_skip = bool(self.px_bg_skip.get())
        c.pixel_smart_skip = bool(self.px_smart_skip.get())
        c.pixel_color_tolerance = int(self.px_tolerance.get())
        c.pixel_batch_size = int(self.px_batch.get())
        c.pixel_image_path = self.px_image.get().strip()
        c.pixel_site_url = self.px_site_url.get().strip()
        c.pixel_username = self.px_username.get().strip()
        c.pixel_password = self.px_password.get().strip()
        c.pixel_wait_for_login = bool(self.px_wait_login.get())
        # Multi-account: đồng bộ từ danh sách dòng.
        accounts = self._collect_accounts()
        if accounts:
            # Dòng đầu -> acc chính (pixel_username/pixel_password).
            c.pixel_username, c.pixel_password = accounts[0]
            # Các dòng còn lại -> chuỗi 'user|pass;...'.
            extras = accounts[1:]
            c.pixel_multi_accounts = ";".join(f"{u}|{p}" for u, p in extras)
            c.pixel_num_accounts = len(accounts)
        else:
            c.pixel_multi_accounts = ""
            c.pixel_num_accounts = 1
        return c

    def _save(self):
        cfgmod.save(self._collect())
        self._log("Đã lưu cài đặt vào config.yaml.")

    # ---------------- Logging ----------------
    def _log(self, msg: str):
        self.log_queue.put(str(msg))

    def _poll_logs(self):
        try:
            while True:
                msg = self.log_queue.get_nowait()
                if self.log_box is not None:
                    self.log_box.insert(END, msg + "\n")
                    self.log_box.see(END)
                else:
                    # Không còn khung Nhật ký -> in ra console.
                    print(msg, flush=True)
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
            # Đăng ký ESC (không cần modifier)
            ok = user32.RegisterHotKey(None, HOTKEY_ID, MOD_NOREPEAT, VK_ESCAPE)
            if not ok:
                # Thử Ctrl+ESC fallback? ESC đơn thường OK. Nếu fail thì vẫn có nút Hủy.
                return
            msg = w.MSG()
            while True:
                # GetMessage block cho đến khi có hotkey
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
