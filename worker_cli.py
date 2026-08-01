"""Worker CLI — chạy 1 tài khoản tô 1 dải cột. Độc lập, không import GUI.

Được multi_account.py gọi qua subprocess để tránh lỗi re-import __main__ của
multiprocessing.spawn (process con không mở lại GUI).

Cách gọi:
    python worker_cli.py <config_file.json>

config_file.json chứa:
    {
      "cfg": {...},            # dict từ Config
      "username": "...",
      "password": "...",
      "acc_index": 0,
      "n_accounts": 2,
      "cells": [[x,y,[r,g,b]], ...],   # danh sách ô đầy đủ của bức ảnh
      "grid_w": 512, "grid_h": 320,
      "x_start": 0, "x_end": 99,
      "progress_path": "pixel_progress_acc1.json",
      "stop_file": ".../.multi_stop_flag"
    }

Log ghi ra stdout (mỗi dòng 1 message). GUI đọc realtime.
"""
from __future__ import annotations

import json
import os
import sys
import time

# Khi đóng gói exe, Playwright tính đường dẫn browser (.local-browsers) theo vị
# trí driver bundle trong _internal/ -> không thấy browser đã cài.
# Force dùng cache user mặc định. Phải đặt TRƯỚC khi import playwright.
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "0")

# Đảm bảo import được các module cùng thư mục (chỉ cần khi chạy từ source;
# khi đóng gói exe, các module đã được bundle vào sys.path sẵn).
if not getattr(sys, "frozen", False):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _log(msg: str):
    """Ghi log ra stdout, flush ngay để GUI đọc realtime."""
    try:
        sys.stdout.write(msg + "\n")
        sys.stdout.flush()
    except Exception:
        pass


# File log riêng cho worker (để debug khi GUI log không thấy). Mỗi acc 1 file.
_WORKER_LOG_FILE = ""


def _file_log(msg: str):
    """Ghi log ra file .multi_accN.log (song song với stdout)."""
    global _WORKER_LOG_FILE
    if not _WORKER_LOG_FILE:
        return
    try:
        import datetime
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        with open(_WORKER_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


def main():
    if len(sys.argv) < 2:
        sys.stderr.write("Usage: python worker_cli.py <config_file.json>\n")
        sys.exit(2)

    config_file = sys.argv[1]
    with open(config_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    acc_index = data["acc_index"]
    n_accounts = data["n_accounts"]
    username = data["username"]
    password = data["password"]
    grid_w = data["grid_w"]
    grid_h = data["grid_h"]
    x_start = data["x_start"]
    x_end = data["x_end"]
    progress_path = data["progress_path"]
    stop_file = data.get("stop_file", "")
    cfg_dict = data["cfg"]
    cells_serialized = data["cells"]

    tag = f"[A{acc_index + 1}/{n_accounts}]"

    # File log riêng cho acc này (để debug khi GUI log không đủ).
    global _WORKER_LOG_FILE
    try:
        log_dir = os.path.dirname(os.path.abspath(config_file))
        _WORKER_LOG_FILE = os.path.join(log_dir, f".multi_acc{acc_index + 1}.log")
        # Xóa log cũ đầu mỗi lần chạy.
        try:
            os.remove(_WORKER_LOG_FILE)
        except Exception:
            pass
    except Exception:
        _WORKER_LOG_FILE = ""

    def log(msg: str):
        _log(f"{tag} {msg}")
        _file_log(f"{tag} {msg}")

    log(f"▶ Worker acc{acc_index + 1} (PID {os.getpid()}) khởi động, user={username}.")

    # Cờ dừng qua file (process không chia memory).
    # QUAN TRỌNG: trong multi-account, KHÔNG đọc screen_painter.STOP_FLAG vì đó
    # là biến toàn cục dùng chung giữa các acc (nếu 1 acc tác động -> tất cả dừng).
    # Chỉ đọc file stop do multi_account cha đặt khi ESC thật sự.
    def is_stopped() -> bool:
        if stop_file:
            try:
                return os.path.exists(stop_file)
            except Exception:
                pass
        return False

    # Monkey-patch dom_painter để nhận file stop chính xác VÀ không dùng
    # screen_painter.STOP_FLAG (biến chung gây dừng nhầm acc khác).
    try:
        import dom_painter as dp
        _worker_stop_file = stop_file or dp._MULTI_STOP_FILE
        dp._MULTI_STOP_FILE = _worker_stop_file

        def _worker_should_stop() -> bool:
            # Chỉ đọc file stop do multi_account cha đặt khi ESC -> không nhầm acc khác.
            try:
                return os.path.exists(_worker_stop_file)
            except Exception:
                return False

        dp._should_stop = _worker_should_stop
    except Exception:
        pass

    try:
        from config import Config
        import pixel_painter as pp
        import dom_painter
        import browser as br

        # Khởi tạo lại Config từ dict.
        cfg = Config(**{k: v for k, v in cfg_dict.items()
                        if k in Config.__dataclass_fields__})
        cfg.pixel_username = username
        cfg.pixel_password = password
        cfg.session_dir = data.get("session_base", cfg.session_dir)
        if acc_index:
            cfg.session_dir = cfg.session_dir + f"_acc{acc_index + 1}"

        # Báo cáo chi tiết khi khởi động: grid config của ảnh (kích thước resize),
        # dải cột phụ trách. Grid thật của canvas sẽ auto-detect sau khi mở trang.
        log(f"📊 Báo cáo khởi động:")
        log(f"    • Grid config (ảnh nguồn resize): {grid_w}×{grid_h}")
        log(f"    • Grid canvas thật: sẽ auto-detect sau khi mở trang (site có thể đổi kích thước).")

        # Lọc ô trong dải cột của acc này.
        cells_all = [pp.Cell(x=c[0], y=c[1], rgb=tuple(c[2])) for c in cells_serialized]
        log(f"    • Tổng ô toàn ảnh: {len(cells_all)}")
        if cells_all:
            xmin = min(c.x for c in cells_all)
            xmax = max(c.x for c in cells_all)
            ymin = min(c.y for c in cells_all)
            ymax = max(c.y for c in cells_all)
            log(f"    • Phạm vi ô thật: x {xmin}-{xmax}, y {ymin}-{ymax}")
        sub_cells = pp.filter_cells_by_x(cells_all, x_start, x_end)
        log(f"    • Acc này phụ trách cột {x_start}-{x_end}: {len(sub_cells)} ô.")
        if not sub_cells:
            log("⚠️ Không có ô trong dải cột -> nhảy thẳng HELP MODE (phụ acc khác).")

        # Plan riêng cho acc này (resume từ file riêng).
        plan = pp.PixelPlan.load(progress_path, cfg)
        # Bỏ progress cũ nếu grid khác hiện tại (tránh resume sai lệch kích thước).
        if plan is not None and (plan.grid_w != grid_w or plan.grid_h != grid_h):
            log(f"⚠️ Progress cũ dùng grid {plan.grid_w}×{plan.grid_h} khác hiện tại "
                f"{grid_w}×{grid_h} → tạo plan mới.")
            plan = None
        if plan is None or not plan.cells:
            # Lần đầu (chưa có progress) -> tạo plan mới với cells của dải cột.
            plan = pp.PixelPlan(
                cells=sub_cells,
                grid_w=grid_w,
                grid_h=grid_h,
                progress_path=progress_path,
                image_sig=pp._image_signature(cfg),
            )
            log(f"Tạo plan mới: {len(sub_cells)} ô (cột {x_start}-{x_end}).")
        else:
            rt = len(plan.rate_times) if plan.rate_times else 0
            # Nếu đã vẽ hết -> KHÔNG tạo plan mới tô lại, mà giữ nguyên để vào
            # HELP MODE (re-scan canvas, chỉ tô ô thực sự sai màu). Tránh bug
            # "tắt mở lại tô lại hoàn toàn" khi setup không đổi.
            if plan.index >= len(plan.cells):
                log(f"📂 Resume: đã tô hết {plan.index}/{len(plan.cells)} ô đợt trước "
                    f"→ sẽ re-scan canvas và chỉ tô ô còn sai màu (HELP MODE).")
                # Đặt index về 0 để paint_dom không bỏ qua (nhưng cells rỗng ->
                # paint_dom sẽ return ngay, sau đó HELP MODE xử lý).
                plan.cells = []  # rỗng -> paint_dom không làm gì -> vào HELP MODE
            else:
                log(f"📂 Resume: {plan.index}/{len(plan.cells)} ô · {rt} ô trong 5 phút qua.")

        mgr = br.BrowserManager(cfg.session_dir, headless=False)
        try:
            mgr.start()
            page = mgr.new_page()
            log(f"🔑 Đang đăng nhập user={username} (session={cfg.session_dir})...")
            ok = dom_painter.login_and_open_canvas(page, cfg, log)
            if not ok:
                log(f"❌ Không vào được trang canvas (user={username}). "
                    "Chrome vẫn mở — bạn tự login rồi chạy lại acc này.")
                while not is_stopped():
                    time.sleep(1)
                return
            log(f"✅ Login OK user={username}.")
            ci = dom_painter.get_canvas_info(page, log)
            if ci is None:
                log("❌ Không thấy canvas.")
                return
            log(f"✅ Canvas {ci.canvas_w}×{ci.canvas_h}, grid thật auto-detect "
                f"{ci.grid_w}×{ci.grid_h}. Bắt đầu tô "
                f"{plan.remaining()} ô (cột {x_start}-{x_end}).")

            # Phủ ảnh gốc lên canvas (overlay) để xem ảnh tham chiếu khi vẽ.
            dom_painter.show_image_overlay(page, ci, cfg, log)

            page_palette = dom_painter.read_palette(page)
            drawn = dom_painter.paint_dom(
                page, cfg, plan, ci, page_palette,
                log=log, batch_size=0,
            )
            log(f"✅ Xong phần acc này: đã tô {drawn} ô · Tổng {plan.index}/{len(plan.cells)}.")

            # ─────────────────────────────────────────────────────────────
            # HELP MODE: acc xong phần mình sớm -> phụ tô NỐT ô sai màu trên
            # TOÀN bức tranh (của acc khác đang bị rate-limit), dùng quota
            # rate-limit RIÊNG của acc này. Tránh acc chậm phải chờ 5 phút
            # một mình trong khi quota acc nhanh còn thừa bỏ không.
            # Re-scan canvas mỗi vòng -> các acc help không đè nhau (ô nào
            # đúng màu rồi thì bỏ qua).
            #
            # QUAN TRỌNG: đọc canvas theo GRID THẬT auto-detect từ CanvasInfo
            # (ci.grid_w/ci.grid_h, site có thể đổi kích thước canvas) chứ
            # KHÔNG theo grid config (có thể nhỏ hơn vd 100×180) và không
            # hardcode (cũ: 384×240). Cell có tọa độ canvas tuyệt đối.
            # ─────────────────────────────────────────────────────────────
            CANVAS_GW, CANVAS_GH = ci.grid_w, ci.grid_h
            log("🤝 Chuyển HELP MODE: dò ô sai màu toàn ảnh để tô phụ "
                f"(đọc canvas {CANVAS_GW}×{CANVAS_GH} thật).")
            idle = 0  # số vòng liên tiếp không tô được gì (rate-limit)
            read_err = 0  # số lần lỗi đọc canvas liên tiếp
            while not is_stopped():
                try:
                    current = dom_painter.read_canvas_pixels(page, CANVAS_GW, CANVAS_GH)
                    read_err = 0
                except Exception as e:
                    msg = str(e)
                    # Page/Chrome đã đóng thật -> không retry nữa (tránh lặp vô tận).
                    if ("Target page" in msg or "Target context" in msg
                            or "Browser has been closed" in msg
                            or "Target closed" in msg):
                        log(f"[Help] Page/Chrome đã đóng ({msg}) — thoát HELP MODE.")
                        break
                    read_err += 1
                    if read_err >= 3:
                        log(f"[Help] Lỗi đọc canvas {read_err} lần liên tiếp ({msg}) — "
                            f"thoát HELP MODE.")
                        break
                    log(f"[Help] Lỗi đọc canvas: {e} — chờ 30s rồi thử lại "
                        f"(lần {read_err}/3).")
                    for _ in range(30):
                        if is_stopped():
                            break
                        time.sleep(1)
                    continue
                log(f"[Help] Đọc canvas xong: {len(current)} ô (keys sample: "
                    f"{list(current.keys())[:3]}).")
                # Tìm ô của TOÀN bức tranh vẫn sai màu (không phân biệt dải acc).
                wrong = []
                missing = 0
                for c in cells_all:
                    cur = current.get((c.x, c.y))
                    if cur is None:
                        # Ô ngoài canvas thật (offset đẩy xa) -> không thể help, bỏ qua.
                        missing += 1
                        continue
                    if pp._color_dist(cur, c.rgb) > cfg.pixel_color_tolerance:
                        wrong.append(c)
                if missing:
                    log(f"[Help] {missing} ô nằm ngoài canvas thật -> bỏ qua (không help được).")
                if not wrong:
                    log("✅ Bức tranh hoàn tất — không còn ô sai màu.")
                    break
                log(f"[Help] Còn {len(wrong)} ô sai màu toàn ảnh -> "
                    f"acc này phụ trách tô (quota riêng).")
                help_plan = pp.PixelPlan(
                    cells=wrong, index=0,
                    grid_w=grid_w, grid_h=grid_h,
                    progress_path="",  # help không lưu progress (linh hoạt)
                )
                drawn_help = dom_painter.paint_dom(
                    page, cfg, help_plan, ci, page_palette,
                    log=log, batch_size=0,
                )
                log(f"[Help] Đã tô phụ {drawn_help} ô cho cả nhóm.")
                if drawn_help == 0:
                    # acc này cũng dính rate-limit -> chờ rồi dò lại.
                    idle += 1
                    if idle >= 5:
                        log("[Help] Rate-limit toàn nhóm sau 5 lần chờ — dừng help.")
                        break
                    log(f"[Help] Rate-limit — chờ 60s rồi dò lại (lần {idle}/5).")
                    for _ in range(60):
                        if is_stopped():
                            break
                        time.sleep(1)
                else:
                    idle = 0
            # Gỡ overlay khi hoàn tất / dừng.
            dom_painter.hide_image_overlay(page)
            try:
                page.close()
            except Exception:
                pass
        finally:
            try:
                mgr.close()
            except Exception:
                pass
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        log(f"❌ Lỗi worker: {e}")
        log(tb)
        # Giữ Chrome mở khi có lỗi để người dùng xem được (không đóng vội).
        log("⏸ Chrome vẫn mở để bạn xem lỗi. Nhấn ESC trên GUI để đóng hết.")
        try:
            while not is_stopped():
                time.sleep(1)
        except Exception:
            pass


if __name__ == "__main__":
    main()
