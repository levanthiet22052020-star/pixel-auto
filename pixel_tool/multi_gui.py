"""Giao diện đồ họa (Tkinter) cho Multi-account Pixel Painter — BẢN ĐƠN GIẢN.

Người dùng chỉ cần nhập:
  - Ảnh nguồn
  - Kích thước lưới + vị trí bắt đầu vẽ (X, Y) + thời gian chờ
  - Danh sách tài khoản: mỗi acc chỉ cần Tên + Mật khẩu

Tool tự lo:
  - session_dir (theo tên acc)
  - chia cột đều cho N acc
  - proxy (để trống)
  - cooldown / jitter mặc định hợp lý
"""
from __future__ import annotations

import os
import queue
import threading
from tkinter import (
    Tk, ttk, StringVar, BooleanVar, IntVar, filedialog, messagebox, scrolledtext,
)
from tkinter.constants import *

import yaml

import multi_painter as mp
from paths import app_dir


class App:
    def __init__(self, root: Tk):
        self.root = root
        self.root.title("Multi-account Pixel Painter")
        self.root.geometry("640x720")
        self.root.minsize(580, 660)
        self.log_queue: queue.Queue[str] = queue.Queue()

        # --- Cài đặt chung (giống exe cũ) ---
        self.image = StringVar()
        self.site_url = StringVar(value="https://datn.unifolio.io.vn")
        self.pixel_url = StringVar(value="https://datn.unifolio.io.vn/pixel")
        self.grid_w = IntVar(value=100)
        self.grid_h = IntVar(value=100)
        self.offset_x = IntVar(value=0)
        self.offset_y = IntVar(value=0)
        self.cooldown = StringVar(value="0.0")
        self.jitter = StringVar(value="0.2")
        self.batch = IntVar(value=0)
        self.start_delay = StringVar(value="5")
        self.smart_skip = BooleanVar(value=True)
        self.dither = BooleanVar(value=False)
        self.bg_skip = BooleanVar(value=False)
        self.tolerance = IntVar(value=24)
        self.headless = BooleanVar(value=False)

        # Danh sách acc: mỗi acc = {"name": ..., "password": ...}.
        # Chỉ 2 trường user cần nhập — còn lại tool tự lo.
        self.acc_rows: list[dict] = []  # [{name_var, pass_var}, ...]

        # Trạng thái chạy.
        self.running = False

        self._build_ui()
        self._poll_logs()
        self._load_default_config()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------- UI
    def _build_ui(self):
        pad = {"padx": 8, "pady": 4}

        # Thanh nút điều khiển (TRÊN CÙNG) — luôn thấy, không phụ thuộc cuộn.
        # Style cho nút Chạy (xanh đậm, chữ đen to).
        try:
            style = ttk.Style()
            style.configure("Run.TButton", font=("Segoe UI", 12, "bold"),
                            foreground="black", background="#16a34a")
        except Exception:
            pass

        bar = ttk.Frame(self.root)
        bar.pack(fill=X, padx=8, pady=(8, 4), side=TOP)
        self.btn_run = ttk.Button(bar, text="▶  VẼ SONG SONG", command=self._start_paint,
                                  style="Run.TButton", padding=(24, 12))
        self.btn_run.pack(side=LEFT, padx=4)
        self.btn_stop = ttk.Button(bar, text="⏹ Dừng", command=self._stop, state=DISABLED,
                                   padding=(10, 6))
        self.btn_stop.pack(side=LEFT, padx=4)
        ttk.Separator(bar, orient=VERTICAL).pack(side=LEFT, fill=Y, padx=6)
        ttk.Button(bar, text="🔍 Dry-run", command=self._dry_run).pack(side=LEFT, padx=4)
        ttk.Button(bar, text="🗑 Xoá tiến độ", command=self._reset).pack(side=LEFT, padx=4)
        ttk.Separator(bar, orient=VERTICAL).pack(side=LEFT, fill=Y, padx=6)
        ttk.Button(bar, text="💾 Lưu", command=self._save).pack(side=LEFT, padx=4)

        # Status ngay dưới thanh nút.
        self.status = StringVar(value="Sẵn sàng.")
        ttk.Label(self.root, textvariable=self.status, anchor=W,
                  font=("Segoe UI", 9, "bold")).pack(fill=X, padx=12, pady=(0, 2))

        # Notebook (tab) chiếm phần còn lại.
        n = ttk.Notebook(self.root)
        n.pack(fill=BOTH, expand=True, padx=8, pady=4)

        self._build_main_tab(n)

        # Tab Nhật ký.
        log_tab = ttk.Frame(n)
        n.add(log_tab, text="2. Nhật ký")
        self.log_box = scrolledtext.ScrolledText(
            log_tab, height=22, wrap=WORD, font=("Consolas", 9))
        self.log_box.pack(fill=BOTH, expand=True, padx=8, pady=8)

    def _build_main_tab(self, n: ttk.Notebook):
        pad = {"padx": 8, "pady": 4}
        outer = ttk.Frame(n)
        n.add(outer, text="1. Cài đặt")

        # Bọc tab trong Canvas + Scrollbar để cuộn khi nội dung dài.
        from tkinter import Canvas as TkCanvas
        canvas = TkCanvas(outer, highlightthickness=0, borderwidth=0)
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

        # --- Ảnh nguồn ---
        src = ttk.LabelFrame(tab, text="🖼 Ảnh nguồn")
        src.pack(fill=X, **pad)
        row = ttk.Frame(src)
        row.pack(fill=X, padx=6, pady=4)
        ttk.Entry(row, textvariable=self.image, width=42).pack(side=LEFT, fill=X, expand=True)
        ttk.Button(row, text="Chọn ảnh...", command=self._pick_image).pack(side=LEFT, padx=(4, 0))

        # --- URL trang ---
        url = ttk.LabelFrame(tab, text="🌐 Địa chỉ trang")
        url.pack(fill=X, **pad)
        ttk.Label(url, text="URL trang chính (đăng nhập):").grid(row=0, column=0, sticky=W, padx=6, pady=4)
        ttk.Entry(url, textvariable=self.site_url, width=40).grid(row=0, column=1, sticky=EW, padx=6, pady=4)
        ttk.Label(url, text="URL trang pixel (canvas):").grid(row=1, column=0, sticky=W, padx=6, pady=4)
        ttk.Entry(url, textvariable=self.pixel_url, width=40).grid(row=1, column=1, sticky=EW, padx=6, pady=4)
        ttk.Label(url, text="Tool đăng nhập trang chính rồi tự chuyển sang trang pixel để vẽ.",
                  foreground="gray").grid(row=2, column=0, columnspan=2, sticky=W, padx=6)
        url.columnconfigure(1, weight=1)

        # --- Kích thước + vị trí vẽ (như exe) ---
        gr = ttk.LabelFrame(tab, text="📏 Kích thước & vị trí vẽ (canvas thật 384×240)")
        gr.pack(fill=X, **pad)
        ttk.Label(gr, text="Rộng ảnh (ô):").grid(row=0, column=0, sticky=W, padx=6, pady=4)
        ttk.Spinbox(gr, from_=2, to=384, textvariable=self.grid_w, width=8).grid(row=0, column=1, sticky=W, padx=6)
        ttk.Label(gr, text="Cao ảnh (ô):").grid(row=0, column=2, sticky=W, padx=6, pady=4)
        ttk.Spinbox(gr, from_=2, to=240, textvariable=self.grid_h, width=8).grid(row=0, column=3, sticky=W, padx=6)
        ttk.Label(gr, text="→ Vẽ từ ô X:").grid(row=1, column=0, sticky=W, padx=6, pady=4)
        ttk.Spinbox(gr, from_=0, to=383, textvariable=self.offset_x, width=8).grid(row=1, column=1, sticky=W, padx=6)
        ttk.Label(gr, text="Y:").grid(row=1, column=2, sticky=W, padx=6, pady=4)
        ttk.Spinbox(gr, from_=0, to=239, textvariable=self.offset_y, width=8).grid(row=1, column=3, sticky=W, padx=6)

        # --- Thời gian & tốc độ ---
        tm = ttk.LabelFrame(tab, text="⏱ Thời gian & tốc độ")
        tm.pack(fill=X, **pad)
        ttk.Label(tm, text="Chờ trước khi vẽ (giây):").grid(row=0, column=0, sticky=W, padx=6, pady=4)
        ttk.Entry(tm, textvariable=self.start_delay, width=6).grid(row=0, column=1, sticky=W, padx=6)
        ttk.Label(tm, text="(đếm ngược để bạn theo dõi)", foreground="gray").grid(row=0, column=2, columnspan=2, sticky=W, padx=6)
        ttk.Label(tm, text="Cooldown (giây):").grid(row=1, column=0, sticky=W, padx=6, pady=4)
        ttk.Entry(tm, textvariable=self.cooldown, width=6).grid(row=1, column=1, sticky=W, padx=6)
        ttk.Label(tm, text="Nhiễu ± (giây):").grid(row=1, column=2, sticky=W, padx=6, pady=4)
        ttk.Entry(tm, textvariable=self.jitter, width=6).grid(row=1, column=3, sticky=W, padx=6)
        ttk.Label(tm, text="Vẽ từng mẻ (0=vẽ hết):").grid(row=2, column=0, sticky=W, padx=6, pady=4)
        ttk.Spinbox(tm, from_=0, to=100000, textvariable=self.batch, width=8).grid(row=2, column=1, sticky=W, padx=6)

        # --- Tùy chọn ---
        opt = ttk.LabelFrame(tab, text="⚙️ Tùy chọn")
        opt.pack(fill=X, **pad)
        ttk.Checkbutton(opt, text="Smart skip (bỏ ô đã đúng màu)", variable=self.smart_skip).grid(row=0, column=0, sticky=W, padx=6, pady=4)
        ttk.Checkbutton(opt, text="Dithering", variable=self.dither).grid(row=0, column=1, sticky=W, padx=6, pady=4)
        ttk.Checkbutton(opt, text="Bỏ ô nền trắng/đen", variable=self.bg_skip).grid(row=1, column=0, sticky=W, padx=6, pady=4)
        ttk.Checkbutton(opt, text="Ẩn Chrome (headless)", variable=self.headless).grid(row=1, column=1, sticky=W, padx=6, pady=4)
        ttk.Label(opt, text="Dung sai màu:").grid(row=2, column=0, sticky=W, padx=6, pady=4)
        ttk.Spinbox(opt, from_=0, to=128, textvariable=self.tolerance, width=6).grid(row=2, column=1, sticky=W, padx=6)

        # --- Danh sách tài khoản (chỉ Tên + Mật khẩu) ---
        acc_frame = ttk.LabelFrame(tab, text="👥 Tài khoản datn (chỉ cần Tên + Mật khẩu — tool tự chia cột & mở Chrome)")
        acc_frame.pack(fill=BOTH, expand=True, **pad)

        # Header.
        hdr = ttk.Frame(acc_frame)
        hdr.pack(fill=X, padx=6, pady=(4, 2))
        ttk.Label(hdr, text="Tên đăng nhập", width=22, anchor=W).pack(side=LEFT, padx=(0, 4))
        ttk.Label(hdr, text="Mật khẩu", width=22, anchor=W).pack(side=LEFT, padx=4)
        ttk.Label(hdr, text="(cột tự chia)", foreground="gray").pack(side=LEFT, padx=4)

        # Vùng cuộn chứa các dòng acc.
        scroll_area = ttk.Frame(acc_frame)
        scroll_area.pack(fill=BOTH, expand=True, padx=6, pady=2)
        self.acc_container = ttk.Frame(scroll_area)
        self.acc_container.pack(fill=BOTH, expand=True, anchor=N)

        # Nút thêm/xoá acc.
        ab = ttk.Frame(acc_frame)
        ab.pack(fill=X, padx=6, pady=4)
        ttk.Button(ab, text="➕ Thêm tài khoản", command=self._add_account).pack(side=LEFT, padx=2)
        ttk.Button(ab, text="➖ Xoá cuối", command=self._remove_account).pack(side=LEFT, padx=2)

        # Mặc định tạo 2 dòng.
        if not self.acc_rows:
            self._add_account()
            self._add_account()

        tip = ttk.Label(tab, text=(
            "💡 Cách dùng:\n"
            "  1. Chọn ảnh + cài kích thước/vị trí.\n"
            "  2. Nhập Tên + Mật khẩu các tài khoản datn.\n"
            "  3. Bấm ▶ Vẽ song song — tool tự đăng nhập từng acc, tự chia tranh thành N cột, mỗi acc vẽ 1 cột."
        ), justify=LEFT, foreground="#1d4ed8")
        tip.pack(fill=X, **pad)

    # ----------------------------------------------------- Account rows
    def _add_account(self):
        idx = len(self.acc_rows)
        row_frame = ttk.Frame(self.acc_container)
        row_frame.pack(fill=X, pady=1)
        name_var = StringVar()
        pass_var = StringVar()
        ttk.Entry(row_frame, textvariable=name_var, width=22).pack(side=LEFT, padx=(0, 4))
        ttk.Entry(row_frame, textvariable=pass_var, width=22).pack(side=LEFT, padx=4)
        col_label = StringVar(value="(chưa chia)")
        ttk.Label(row_frame, textvariable=col_label, width=14, foreground="gray").pack(side=LEFT, padx=4)
        self.acc_rows.append({
            "frame": row_frame,
            "name_var": name_var,
            "pass_var": pass_var,
            "col_var": col_label,
        })

    def _remove_account(self):
        if not self.acc_rows:
            return
        row = self.acc_rows.pop()
        row["frame"].destroy()

    def _refresh_col_labels(self, accounts):
        """Cập nhật nhãn cột sau khi auto-split."""
        for row, acc in zip(self.acc_rows, accounts):
            row["col_var"].set(f"{acc.x_start}-{acc.x_end}")

    # ----------------------------------------------------- File I/O
    def _collect(self) -> dict:
        accounts = []
        for i, row in enumerate(self.acc_rows):
            name = row["name_var"].get().strip()
            pwd = row["pass_var"].get().strip()
            if not name:
                continue  # bỏ dòng trống
            accounts.append({
                "name": f"acc{i+1}",          # tên nội bộ
                "session_dir": "",            # tool tự lo
                "username": name,
                "password": pwd,
                "proxy": "",                  # tool tự lo
            })
        return {
            "image": self.image.get(),
            "grid": f"{self.grid_w.get()}x{self.grid_h.get()}",
            "headless": self.headless.get(),
            "auto_repair": False,
            "palette": "",
            "dither": self.dither.get(),
            "bg_skip": self.bg_skip.get(),
            "smart_skip": self.smart_skip.get(),
            "color_tolerance": self.tolerance.get(),
            "cooldown_seconds": self.cooldown.get(),
            "jitter_seconds": self.jitter.get(),
            "batch_size": self.batch.get(),
            "offset_x": self.offset_x.get(),
            "offset_y": self.offset_y.get(),
            "start_delay_seconds": self.start_delay.get(),
            "pixel_site_url": self.site_url.get().strip(),
            "pixel_url": self.pixel_url.get().strip(),
            "accounts": accounts,
        }

    def _apply_dict(self, data: dict):
        if data.get("image"):
            self.image.set(data["image"])
        if data.get("pixel_site_url"):
            self.site_url.set(data["pixel_site_url"])
        if data.get("pixel_url"):
            self.pixel_url.set(data["pixel_url"])
        gw, gh = mp._parse_grid(str(data.get("grid", "100x100")))
        self.grid_w.set(gw)
        self.grid_h.set(gh)
        self.offset_x.set(int(data.get("offset_x", 0)))
        self.offset_y.set(int(data.get("offset_y", 0)))
        self.cooldown.set(str(data.get("cooldown_seconds", "0.0")))
        self.jitter.set(str(data.get("jitter_seconds", "0.2")))
        self.batch.set(int(data.get("batch_size", 0)))
        self.start_delay.set(str(data.get("start_delay_seconds", "5")))
        self.smart_skip.set(bool(data.get("smart_skip", True)))
        self.dither.set(bool(data.get("dither", False)))
        self.bg_skip.set(bool(data.get("bg_skip", False)))
        self.tolerance.set(int(data.get("color_tolerance", 24)))
        self.headless.set(bool(data.get("headless", False)))

        # Nạp lại danh sách acc (chỉ user/pass).
        accts = data.get("accounts", []) or []
        # Xoá hết dòng cũ.
        while self.acc_rows:
            r = self.acc_rows.pop()
            r["frame"].destroy()
        for a in accts:
            self._add_account()
            self.acc_rows[-1]["name_var"].set(a.get("username", ""))
            self.acc_rows[-1]["pass_var"].set(a.get("password", ""))
        if not self.acc_rows:
            self._add_account()
            self._add_account()

    def _default_config_path(self) -> str:
        return os.path.join(app_dir(), "accounts.yaml")

    def _load_default_config(self):
        p = self._default_config_path()
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    self._apply_dict(yaml.safe_load(f) or {})
                self._log(f"📂 Đã tải {p}")
            except Exception as e:
                self._log(f"[Cảnh báo] không load accounts.yaml: {e}")

    def _save(self):
        data = self._collect()
        p = self._default_config_path()
        with open(p, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
        self._log(f"💾 Đã lưu {p}")

    def _pick_image(self):
        p = filedialog.askopenfilename(
            title="Chọn ảnh nguồn",
            filetypes=[("Ảnh", "*.png *.jpg *.jpeg *.bmp *.gif"), ("Tất cả", "*.*")],
            initialdir=app_dir())
        if p:
            self.image.set(p)

    # ----------------------------------------------------- Chạy
    def _build_mc(self) -> mp.MultiConfig:
        """Lưu tạm config ra file rồi load qua multi_painter (resolve đường dẫn)."""
        p = os.path.join(app_dir(), ".accounts_runtime.yaml")
        with open(p, "w", encoding="utf-8") as f:
            yaml.safe_dump(self._collect(), f, allow_unicode=True, sort_keys=False)
        return mp.load_multi_config(p)

    def _validate_accounts(self) -> bool:
        valid = [r for r in self.acc_rows if r["name_var"].get().strip()]
        if not valid:
            messagebox.showwarning("Thiếu tài khoản",
                                   "Vui lòng nhập ít nhất 1 Tên đăng nhập.")
            return False
        # Cảnh báo nếu thiếu mật khẩu.
        missing = [r for r in valid if not r["pass_var"].get().strip()]
        if missing:
            if not messagebox.askyesno(
                "Thiếu mật khẩu",
                f"Có {len(missing)} acc chưa nhập mật khẩu. Tool sẽ mở Chrome để bạn tự "
                "đăng nhập tay. Tiếp tục?"):
                return False
        return True

    def _start_paint(self, dry_run: bool = False, only: str = None):
        if self.running:
            return
        if not self._validate_accounts():
            return
        try:
            mc = self._build_mc()
        except Exception as e:
            messagebox.showerror("Lỗi cấu hình", str(e))
            return
        if not dry_run and not mc.image:
            messagebox.showwarning("Thiếu ảnh", "Vui lòng chọn ảnh nguồn.")
            return
        if not mc.accounts:
            messagebox.showwarning("Thiếu tài khoản", "Không có tài khoản hợp lệ.")
            return

        # Tự chia cột đều cho N acc.
        mp.auto_split_columns(mc.accounts, mc.grid_w, self._qprint)
        self._refresh_col_labels(mc.accounts)

        self.running = True
        self.btn_run.config(state=DISABLED)
        self.btn_stop.config(state=NORMAL)
        self.status.set("Đang chạy..." if not dry_run else "Dry-run...")

        # Chạy multi_painter.paint_all trong thread, log qua queue.
        def worker():
            self._patch_print()
            try:
                rc = mp.paint_all(mc, reset=False, only=only, dry_run=dry_run)
            except Exception as e:
                self._ui_log(f"❌ Lỗi: {e}")
                import traceback
                self._ui_log(traceback.format_exc())
            finally:
                self._restore_print()
                self.running = False
                self.root.after(0, self._on_run_done)

        threading.Thread(target=worker, daemon=True).start()

    def _on_run_done(self):
        self.btn_run.config(state=NORMAL)
        self.btn_stop.config(state=DISABLED)
        self.status.set("Xong.")

    def _stop(self):
        self._ui_log("⏹ Đã yêu cầu dừng...")
        try:
            import screen_painter as sp
            sp.request_stop()
        except Exception:
            pass
        self.status.set("Đang dừng...")

    def _dry_run(self):
        self._start_paint(dry_run=True)

    def _reset(self):
        if not messagebox.askyesno("Xác nhận", "Xoá tiến độ tất cả acc?"):
            return
        try:
            mc = self._build_mc()
            mp.auto_split_columns(mc.accounts, mc.grid_w, self._qprint)
            for a in mc.accounts:
                p = os.path.join(mc.progress_dir, f"{a.name}.json")
                if os.path.exists(p):
                    os.remove(p)
                    self._log(f"🗑 Đã xoá {p}")
            self._log("✅ Đã xoá toàn bộ tiến độ.")
        except Exception as e:
            messagebox.showerror("Lỗi", str(e))

    # ----------------------------------------------------- Logging
    def _qprint(self, *args, **kwargs):
        import io
        buf = io.StringIO()
        kwargs["file"] = buf
        kwargs["end"] = ""
        try:
            print(*args, **kwargs)
        except Exception:
            pass
        t = buf.getvalue()
        if t.strip():
            self._ui_log(t.rstrip("\n"))

    def _patch_print(self):
        import builtins
        self._orig_print = builtins.print
        builtins.print = self._qprint

    def _restore_print(self):
        import builtins
        if hasattr(self, "_orig_print"):
            builtins.print = self._orig_print

    def _ui_log(self, msg: str):
        self.log_queue.put(str(msg))

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

    def _on_close(self):
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
