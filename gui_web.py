"""Web UI cho Auto Pixel Painter — chạy qua pywebview (Edge Chromium).

Giao diện HTML + Tailwind (light mode sạch), bridge JS ↔ Python qua class Api.
Tái dùng 100% logic paint/multi-account từ dom_painter.py + multi_account.py.

Cách chạy:
    python gui_web.py

Khác gui.py (Tkinter): KHÔNG tạo tk widget, chỉ giữ data + method action.
"""
from __future__ import annotations

import base64
import io
import json
import os
import queue
import threading
import time
from typing import Any

import webview

import config as cfgmod
from config import Config


class Api:
    """Bridge JS ↔ Python. Mỗi method trả dict/list/str cho JS."""

    def __init__(self):
        self.cfg = cfgmod.load()
        self.log_queue: queue.Queue[str] = queue.Queue()
        self._progress_pct = 0.0
        self._progress_label = "Chưa có tiến độ."
        self._painting = False
        # Tracking multi-account: tổng số ô cần vẽ + danh sách file progress.
        self._multi_total: int = 0
        self._multi_progress_files: list = []
        self._multi_n_accs: int = 0

    # ---------- helper ----------
    def _log(self, msg: str):
        """Ghi log vào queue, JS sẽ poll."""
        self.log_queue.put(str(msg))
        # Cũng in ra console để debug.
        print(msg, flush=True)

    def _apply_form(self, form_json: str) -> Config:
        """Nhận JSON form từ JS, áp vào cfg, trả Config sẵn sàng dùng."""
        c = self.cfg
        try:
            f = json.loads(form_json) if form_json else {}
        except Exception:
            f = {}
        # Pixel
        c.pixel_image_path = f.get("pixel_image_path", "") or c.pixel_image_path
        c.pixel_site_url = f.get("pixel_site_url", "") or c.pixel_site_url
        c.pixel_username = f.get("pixel_username", "") or c.pixel_username
        c.pixel_password = f.get("pixel_password", "") or c.pixel_password
        c.pixel_wait_for_login = False  # set cứng: luôn auto-login, không chờ thủ công.
        c.pixel_grid_w = int(f.get("pixel_grid_w", c.pixel_grid_w))
        c.pixel_grid_h = int(f.get("pixel_grid_h", c.pixel_grid_h))
        c.pixel_offset_x = int(f.get("pixel_offset_x", c.pixel_offset_x))
        c.pixel_offset_y = int(f.get("pixel_offset_y", c.pixel_offset_y))
        c.pixel_dither = bool(f.get("pixel_dither", c.pixel_dither))
        c.pixel_full_color = bool(f.get("pixel_full_color", c.pixel_full_color))
        c.pixel_bg_skip = bool(f.get("pixel_bg_skip", c.pixel_bg_skip))
        c.pixel_smart_skip = bool(f.get("pixel_smart_skip", c.pixel_smart_skip))
        c.pixel_color_tolerance = int(f.get("pixel_color_tolerance", c.pixel_color_tolerance))
        try:
            c.pixel_overlay_opacity = float(f.get("pixel_overlay_opacity", c.pixel_overlay_opacity))
        except Exception:
            pass
        try:
            c.pixel_cooldown_seconds = float(f.get("pixel_cooldown", c.pixel_cooldown_seconds))
        except Exception:
            pass
        c.pixel_batch_size = int(f.get("pixel_batch_size", c.pixel_batch_size))
        # Accounts: dòng đầu = acc chính, còn lại = pixel_multi_accounts.
        accs = f.get("accounts", [])
        if accs:
            c.pixel_username = accs[0].get("user", "") or c.pixel_username
            c.pixel_password = accs[0].get("pass", "") or c.pixel_password
            extras = accs[1:]
            c.pixel_multi_accounts = ";".join(
                f"{a.get('user','')}|{a.get('pass','')}" for a in extras)
            c.pixel_num_accounts = len(accs)
        c.pixel_use_dom_mode = True
        c.pixel_use_screen_mode = False
        # === GIÁ TRỊ CỨNG (không cho user đổi qua UI) ===
        c.pixel_dither = True           # Dithering
        c.pixel_full_color = True       # Toàn màu
        c.pixel_bg_skip = False         # Bỏ ô nền trắng/đen
        c.pixel_smart_skip = False      # Smart skip
        c.pixel_color_tolerance = 0     # Dung sai màu
        c.pixel_overlay_opacity = 0.4   # Độ mờ overlay
        c.pixel_cooldown_seconds = 0.5  # Cooldown
        c.pixel_batch_size = 0          # Vẽ từng mẻ = 0 (vẽ hết)
        self.cfg = c
        return c

    # ---------- JS API methods ----------
    def get_config(self) -> dict:
        """Trả config hiện tại để JS fill vào form."""
        c = self.cfg
        accs = [{"user": c.pixel_username, "pass": c.pixel_password, "removable": False}]
        if c.pixel_multi_accounts:
            for pair in c.pixel_multi_accounts.split(";"):
                if "|" in pair:
                    u, p = pair.split("|", 1)
                    accs.append({"user": u, "pass": p, "removable": True})
        return {
            "pixel_image_path": c.pixel_image_path,
            "pixel_site_url": c.pixel_site_url,
            "pixel_username": c.pixel_username,
            "pixel_password": c.pixel_password,
            "pixel_wait_login": c.pixel_wait_for_login,
            "pixel_grid_w": c.pixel_grid_w,
            "pixel_grid_h": c.pixel_grid_h,
            "pixel_offset_x": c.pixel_offset_x,
            "pixel_offset_y": c.pixel_offset_y,
            "pixel_dither": c.pixel_dither,
            "pixel_full_color": c.pixel_full_color,
            "pixel_bg_skip": c.pixel_bg_skip,
            "pixel_smart_skip": c.pixel_smart_skip,
            "pixel_color_tolerance": c.pixel_color_tolerance,
            "pixel_overlay_opacity": c.pixel_overlay_opacity,
            "pixel_cooldown_seconds": c.pixel_cooldown_seconds,
            "pixel_batch_size": c.pixel_batch_size,
            "accounts": accs,
        }

    def save_config(self, form_json: str) -> dict:
        """Lưu config.yaml từ form data."""
        c = self._apply_form(form_json)
        cfgmod.save(c)
        return {"ok": True, "message": "✅ Đã lưu config.yaml"}

    def pick_image(self) -> str:
        """Mở file dialog, trả đường dẫn ảnh.

        Dùng tkinter.filedialog (chạy độc lập với UI thread pywebview)
        thay vì win.create_file_dialog — cái sau hay deadlock khi JS await.
        """
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()  # ẩn cửa sổ chính.
            root.attributes("-topmost", True)
            path = filedialog.askopenfilename(
                title="Chọn ảnh nguồn",
                filetypes=[
                    ("Ảnh", "*.png *.jpg *.jpeg *.bmp *.gif *.webp"),
                    ("Tất cả", "*.*"),
                ],
            )
            root.destroy()
            return path or ""
        except Exception as e:
            self._log(f"[pick_image][Lỗi] {e}")
            return ""

    def preview(self, form_json: str) -> str:
        """Tạo preview PNG (ảnh pixel + vị trí canvas) → base64."""
        c = self._apply_form(form_json)
        if not c.pixel_image_path or not os.path.exists(c.pixel_image_path):
            self._log("⚠ Chưa chọn ảnh nguồn.")
            return "Chưa chọn ảnh nguồn."
        try:
            from PIL import Image, ImageDraw
            import pixel_painter as pp
            palette = pp.build_palette(c)
            cells = pp.image_to_pixels(
                c.pixel_image_path, c.pixel_grid_w, c.pixel_grid_h, palette,
                dither=c.pixel_dither, bg_skip=c.pixel_bg_skip,
            )
            gw, gh = c.pixel_grid_w, c.pixel_grid_h
            # Vẽ thumbnail ảnh pixel.
            pix_img = Image.new("RGB", (gw, gh), (255, 255, 255))
            for ce in cells:
                pix_img.putpixel((ce.x, ce.y), tuple(ce.rgb))
            pix_img = pix_img.resize((gw * 4, gh * 4), Image.NEAREST)
            # Ghép vào canvas 512×320 để xem vị trí.
            canvas = Image.new("RGB", (512, 320), (245, 245, 245))
            draw = ImageDraw.Draw(canvas)
            for gx in range(0, 513, 32):
                draw.line([(gx, 0), (gx, 320)], fill=(225, 225, 225))
            for gy in range(0, 321, 32):
                draw.line([(0, gy), (512, gy)], fill=(225, 225, 225))
            thumb = pix_img.resize(
                (max(1, c.pixel_grid_w), max(1, c.pixel_grid_h)), Image.NEAREST)
            canvas.paste(thumb, (c.pixel_offset_x, c.pixel_offset_y))
            draw.rectangle(
                [c.pixel_offset_x, c.pixel_offset_y,
                 c.pixel_offset_x + c.pixel_grid_w - 1,
                 c.pixel_offset_y + c.pixel_grid_h - 1],
                outline=(239, 68, 68), width=1)
            buf = io.BytesIO()
            canvas.save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue()).decode("ascii")
            return f"data:image/png;base64,{b64}"
        except Exception as e:
            self._log(f"[Preview][Lỗi] {e}")
            return f"Lỗi preview: {e}"

    def _paint_dom_thread(self, c: Config, batch: bool):
        """Thread vẽ DOM mode — tái dùng logic dom_painter."""
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
                self._log(f"[DOM] 📂 Resume: {plan.index}/{len(plan.cells)} ô.")
            mgr = br.BrowserManager(c.session_dir, headless=False)
            mgr.start()
            try:
                page = mgr.new_page()
                ok = dp.login_and_open_canvas(page, c, self._log)
                if not ok:
                    self._log("[DOM] Không vào được canvas. Xem Chrome.")
                    return
                ci = dp.get_canvas_info(page, self._log)
                if ci is None:
                    self._log("[DOM][Lỗi] Không thấy canvas.")
                    return
                self._log(f"[DOM] Canvas {ci.canvas_w}×{ci.canvas_h} grid {ci.grid_w}×{ci.grid_h}.")
                dp.show_image_overlay(page, ci, c, self._log)

                def on_progress(done, tot):
                    pct = (done / tot * 100.0) if tot else 0.0
                    self._progress_pct = pct
                    self._progress_label = f"Đã tô {done}/{tot} ô."

                bs = c.pixel_batch_size if batch else 0
                dp.paint_dom(page, c, plan, ci, dp.read_palette(page),
                             log=self._log, batch_size=bs, on_progress=on_progress)
            finally:
                mgr.close()
        except Exception as e:
            self._log(f"[DOM][Lỗi] {e}")
        finally:
            self._painting = False

    def paint_all(self, form_json: str):
        if self._painting:
            self._log("⚠ Đang vẽ rồi. Bấm Hủy trước.")
            return
        c = self._apply_form(form_json)
        if not c.pixel_image_path or not os.path.exists(c.pixel_image_path):
            self._log("⚠ Chọn ảnh nguồn trước.")
            return
        if not c.pixel_site_url:
            self._log("⚠ Nhập URL trang chính (DOM mode).")
            return
        try:
            import screen_painter as sp
            sp.clear_stop()
        except Exception:
            pass
        self._painting = True
        self._progress_pct = 0
        self._multi_total = 0  # thoát chế độ multi progress.
        self._progress_label = "Đang vẽ..."
        self._log(f"[DOM] ▶ Bắt đầu vẽ tất cả ({c.pixel_grid_w}×{c.pixel_grid_h}).")
        threading.Thread(target=self._paint_dom_thread, args=(c, False), daemon=True).start()

    def paint_multi(self, form_json: str):
        if self._painting:
            self._log("⚠ Đang vẽ rồi.")
            return
        c = self._apply_form(form_json)
        if not c.pixel_image_path or not os.path.exists(c.pixel_image_path):
            self._log("⚠ Chọn ảnh nguồn trước.")
            return
        if not c.pixel_site_url:
            self._log("⚠ Nhập URL trang chính.")
            return
        accs_str = ";".join([f"{c.pixel_username}|{c.pixel_password}"])
        if c.pixel_multi_accounts:
            accs_str = accs_str + ";" + c.pixel_multi_accounts
        n = len([a for a in accs_str.split(";") if a.strip()])
        try:
            import screen_painter as sp
            sp.clear_stop()
        except Exception:
            pass
        self._painting = True
        self._progress_pct = 0
        self._progress_label = f"Đang chuẩn bị ({n} tài khoản)..."
        # Tính tổng số ô cần vẽ + danh sách file progress để poll.
        try:
            import pixel_painter as pp
            palette = pp.build_palette(c)
            cells_all = pp.image_to_pixels(
                c.pixel_image_path, c.pixel_grid_w, c.pixel_grid_h, palette,
                dither=c.pixel_dither, bg_skip=c.pixel_bg_skip,
                offset_x=c.pixel_offset_x, offset_y=c.pixel_offset_y,
            )
            self._multi_total = len(cells_all)
            base_dir = cfgmod.app_dir()
            self._multi_progress_files = [
                os.path.join(base_dir, f"pixel_progress_acc{i+1}.json")
                for i in range(n)
            ]
            self._multi_n_accs = n
        except Exception as e:
            self._log(f"[Multi][Lỗi tính progress] {e}")
            self._multi_total = 0
            self._multi_progress_files = []
        self._log(f"[Multi] 🚀 Bắt đầu vẽ đa tài khoản ({n} acc song song, {self._multi_total} ô).")

        def run():
            try:
                import multi_account as ma
                ma.run_multi_account(c, log=self._log)
            except Exception as e:
                self._log(f"[Multi][Lỗi] {e}")
            finally:
                self._painting = False

        threading.Thread(target=run, daemon=True).start()

    def repaint_diff(self, form_json: str):
        """Dò lại canvas rồi tô các ô sai màu (HELP-style)."""
        self._log("🔍 Dò lại & tô: dùng Vẽ tất cả (smart skip sẽ tự bỏ ô đúng màu).")
        c = self._apply_form(form_json)
        c.pixel_smart_skip = True
        self.paint_all(json.dumps({
            "pixel_smart_skip": 1, "pixel_image_path": c.pixel_image_path,
            "pixel_site_url": c.pixel_site_url, "pixel_username": c.pixel_username,
            "pixel_password": c.pixel_password,
            "pixel_grid_w": c.pixel_grid_w, "pixel_grid_h": c.pixel_grid_h,
            "pixel_offset_x": c.pixel_offset_x, "pixel_offset_y": c.pixel_offset_y,
            "pixel_batch_size": c.pixel_batch_size,
        }))

    def cancel(self):
        try:
            import screen_painter as sp
            sp.request_stop()
        except Exception:
            pass
        # Cũng đặt stop flag multi-account.
        try:
            stop_file = os.path.join(cfgmod.app_dir(), ".multi_stop_flag")
            with open(stop_file, "w") as f:
                f.write("1")
        except Exception:
            pass
        self._painting = False
        self._multi_total = 0  # reset progress multi.
        self._log("⏹ Đã yêu cầu dừng.")

    def reset_progress(self) -> str:
        """Xóa toàn bộ file tiến độ: default + multi-account (acc1/2/3...) + loaded."""
        try:
            import glob
            import pixel_painter as pp
            c = self.cfg
            base_dir = cfgmod.app_dir()
            removed = []
            # 1) File default (1 tài khoản).
            path = c.pixel_progress_path or pp._default_progress_path()
            if path and os.path.exists(path):
                os.remove(path)
                removed.append(os.path.basename(path))
            # 2) File multi-account: pixel_progress_acc*.json (mỗi acc 1 file).
            for p in glob.glob(os.path.join(base_dir, "pixel_progress_acc*.json")):
                try:
                    os.remove(p)
                    removed.append(os.path.basename(p))
                except OSError:
                    pass
            # 3) File nạp từ dự án (.pixproj).
            loaded = os.path.join(base_dir, "pixel_progress_loaded.json")
            if os.path.exists(loaded):
                os.remove(loaded)
                removed.append(os.path.basename(loaded))
            if removed:
                self._log(f"🗑 Đã xóa {len(removed)} file progress: {', '.join(removed)}")
            else:
                self._log("ℹ Không có file progress để xóa.")
            self._progress_pct = 0
            self._multi_total = 0
            self._progress_label = "Đã xóa tiến độ."
            return "✅ Đã xóa toàn bộ tiến độ, sẽ vẽ lại từ đầu."
        except Exception as e:
            return f"❌ Lỗi: {e}"

    def project_save(self, form_json: str) -> str:
        """Lưu dự án (.pixproj = setup + ảnh pixel + tiến độ)."""
        c = self._apply_form(form_json)
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            path = filedialog.asksaveasfilename(
                title="Lưu dự án pixel",
                defaultextension=".pixproj",
                filetypes=[("Pixel project", "*.pixproj"), ("Tất cả", "*.*")],
                initialfile="project.pixproj",
            )
            root.destroy()
        except Exception as e:
            return f"❌ Lỗi dialog: {e}"
        if not path:
            return "Đã hủy."
        try:
            import pixel_painter as pp
            import yaml
            palette = pp.build_palette(c)
            plan = pp.PixelPlan.from_image(c, palette)
            cells_serial = [[ce.x, ce.y, list(ce.rgb)] for ce in plan.cells]
            setup = {
                "pixel_image_path": c.pixel_image_path,
                "pixel_site_url": c.pixel_site_url,
                "pixel_username": c.pixel_username,
                "pixel_grid_w": c.pixel_grid_w, "pixel_grid_h": c.pixel_grid_h,
                "pixel_offset_x": c.pixel_offset_x, "pixel_offset_y": c.pixel_offset_y,
                "pixel_smart_skip": c.pixel_smart_skip,
            }
            project = {"setup": setup, "cells": cells_serial, "index": plan.index}
            with open(path, "w", encoding="utf-8") as f:
                json.dump(project, f, ensure_ascii=False)
            return f"✅ Đã lưu dự án: {path}"
        except Exception as e:
            return f"❌ Lỗi lưu: {e}"

    def project_load(self) -> dict:
        """Mở dự án .pixproj."""
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            path = filedialog.askopenfilename(
                title="Mở dự án pixel",
                filetypes=[("Pixel project", "*.pixproj"), ("Tất cả", "*.*")],
            )
            root.destroy()
        except Exception as e:
            return {"message": f"❌ Lỗi dialog: {e}"}
        if not path:
            return {"message": "Đã hủy."}
        try:
            with open(path, "r", encoding="utf-8") as f:
                project = json.load(f)
            setup = project.get("setup", {})
            # Tạo file progress tạm để paint_dom resume.
            cells = project.get("cells", [])
            idx = project.get("index", 0)
            prog_path = os.path.join(cfgmod.app_dir(), "pixel_progress_loaded.json")
            with open(prog_path, "w", encoding="utf-8") as f:
                json.dump({"cells": cells, "index": idx}, f)
            self.cfg.pixel_progress_path = prog_path
            # Trả config để JS fill form.
            c = self.cfg
            for k, v in setup.items():
                if hasattr(c, k):
                    setattr(c, k, v)
            return {
                "message": f"✅ Đã mở dự án: {path} ({len(cells)} ô, tiếp từ {idx})",
                "config": self.get_config(),
            }
        except Exception as e:
            return {"message": f"❌ Lỗi mở: {e}"}

    # ---------- Polling cho JS ----------
    def poll_log(self) -> list:
        """Trả các log mới kể từ lần poll trước."""
        msgs = []
        try:
            while True:
                msgs.append(self.log_queue.get_nowait())
        except queue.Empty:
            pass
        return msgs

    def get_progress(self) -> dict:
        # Chế độ đa tài khoản: đọc index từng file acc, cộng lại.
        if self._multi_total > 0 and self._multi_progress_files:
            import json
            total_done = 0
            for p in self._multi_progress_files:
                try:
                    if os.path.exists(p):
                        with open(p, "r", encoding="utf-8") as f:
                            d = json.load(f)
                        total_done += int(d.get("index", 0))
                except Exception:
                    pass
            pct = (total_done / self._multi_total * 100.0) if self._multi_total else 0.0
            pct = min(pct, 100.0)
            label = f"Đã tô {total_done}/{self._multi_total} ô ({self._multi_n_accs} acc)."
            # Khi xong, reset tracking để không hiện progress cũ.
            if not self._painting and pct >= 99.9:
                pass  # giữ nguyên label "Đã tô X/Y"
            return {"pct": pct, "label": label}
        return {"pct": self._progress_pct, "label": self._progress_label}


def main():
    api = Api()
    html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web_ui.html")
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()
    webview.create_window(
        "Auto Pixel Painter",
        html=html,
        js_api=api,
        width=720, height=840,
        min_size=(640, 600),
        text_select=True,
    )
    # debug=True để mở DevTools (chỉ khi phát triển).
    webview.start(debug=False)


if __name__ == "__main__":
    main()
