"""Multi-account painter — N tài khoản cùng tô 1 bức tranh pixel (CHẠY SONG SONG THẬT).

Cách hoạt động
--------------
• Cùng 1 ảnh nguồn được chia thành N dải cột LIÊN TỤC, KHÔNG chồng nhau.
  Vd ảnh 200 cột, 2 acc -> acc1 tô cột 0..99, acc2 tô cột 100..199.
• Mỗi tài khoản chạy trong 1 PROCESS riêng (multiprocessing) — không phải thread —
  nên 2 acc chạy THẬT SỰ song song (Playwright sync API dựa trên greenlet, nếu dùng
  thread sẽ bị xung đột và chạy đứt ra lần lượt).
• Mỗi acc dùng:
    - Chrome riêng (session_dir khác nhau -> giữ login độc lập)
    - file progress riêng (resume không lẫn acc)
    - cache màu thread-local (trong process đó, không xung đột)
• Log gửi về process cha qua multiprocessing.Queue -> GUI in ra nhật ký.
• Khi 1 acc bị rate-limit (web khóa 600 ô/5 phút cho STUDENT), acc đó tự NGỪNG tô,
  đợi đúng số giây web báo, rồi vẽ tiếp. Các acc khác VẪN chạy (mỗi acc có rate-limit riêng).
• ESC (global hotkey) dừng TẤT CẢ acc: đặt cờ trong file tạm, các process con đọc.

Tài khoản nhập trong GUI: ô "Tài khoản" (acc chính) + các dòng thêm qua
"➕ Thêm tài khoản" (acc phụ). Gộp lại thành list (user, pass).
"""
from __future__ import annotations

import json
import os
import sys
import time
from typing import Callable, Optional

from config import Config, app_dir


# ===========================================================================
# Cờ dừng dùng chung giữa các process (ghi file tạm, vì process không chia memory)
# ===========================================================================
_STOP_FILE = os.path.join(app_dir(), ".multi_stop_flag")


def _set_stop_file(stopped: bool) -> None:
    try:
        if stopped:
            with open(_STOP_FILE, "w") as f:
                f.write("1")
        else:
            if os.path.exists(_STOP_FILE):
                os.remove(_STOP_FILE)
    except Exception:
        pass


def _is_stop_file() -> bool:
    try:
        return os.path.exists(_STOP_FILE)
    except Exception:
        return False


# ===========================================================================
# Parse tài khoản
# ===========================================================================
def parse_accounts(cfg: Config) -> list[tuple[str, str]]:
    """Gộp acc chính (pixel_username) + acc phụ (pixel_multi_accounts) -> [(user, pass), ...].

    acc chính luôn là phần tử đầu tiên. acc phụ parse từ chuỗi
    'user1|pass1;user2|pass2;...'. Trả về list không trùng user.
    """
    accounts: list[tuple[str, str]] = []
    seen: set[str] = set()
    # 1) Acc chính trước.
    if cfg.pixel_username:
        accounts.append((cfg.pixel_username.strip(), cfg.pixel_password))
        seen.add(cfg.pixel_username.strip().lower())
    # 2) Acc phụ từ chuỗi.
    raw = (cfg.pixel_multi_accounts or "").strip()
    if raw:
        for part in raw.split(";"):
            part = part.strip()
            if not part:
                continue
            if "|" in part:
                u, p = part.split("|", 1)
                u, p = u.strip(), p.strip()
            elif ":" in part:
                u, p = part.split(":", 1)
                u, p = u.strip(), p.strip()
            else:
                u, p = part, cfg.pixel_password
            if u and u.lower() not in seen:
                accounts.append((u, p))
                seen.add(u.lower())
    return accounts


def _session_dir_for_acc(base_session: str, acc_index: int) -> str:
    """Thư mục session riêng cho mỗi acc (giữ login độc lập)."""
    if not acc_index:
        return base_session
    return base_session + f"_acc{acc_index + 1}"


# ===========================================================================
# Hàm chính: chạy N subprocess song song
# ===========================================================================
def run_multi_account(
    cfg: Config,
    log: Callable[[str], None] = print,
    on_progress: Optional[Callable[[int, int, int], None]] = None,
) -> dict:
    """Chạy N tài khoản song song (mỗi acc 1 subprocess). Trả về {acc_index: drawn}.

    Dùng subprocess (python worker_cli.py) thay vì multiprocessing để tránh lỗi
    spawn re-import __main__ (process con mở lại GUI).
    """
    import dataclasses
    import subprocess
    import pixel_painter as pp

    # Xóa cờ stop cũ.
    _set_stop_file(False)
    try:
        import screen_painter as sp
        sp.clear_stop()
    except Exception:
        pass

    accounts = parse_accounts(cfg)
    n = len(accounts)
    if n == 0:
        log("[Multi] ❌ Không có tài khoản nào.")
        return {}
    log(f"[Multi] 🚀 Bắt đầu multi-account: {n} tài khoản song song (mỗi acc 1 process).")

    # Sinh danh sách ô đầy đủ.
    if not cfg.pixel_image_path or not os.path.exists(cfg.pixel_image_path):
        log(f"[Multi] ❌ Không thấy ảnh nguồn: {cfg.pixel_image_path}")
        return {}
    palette = pp.build_palette(cfg)
    cells_all = pp.image_to_pixels(
        cfg.pixel_image_path, cfg.pixel_grid_w, cfg.pixel_grid_h, palette,
        dither=cfg.pixel_dither, bg_skip=cfg.pixel_bg_skip,
        offset_x=cfg.pixel_offset_x, offset_y=cfg.pixel_offset_y,
    )
    log(f"[Multi] Bức ảnh: {len(cells_all)} ô trên grid {cfg.pixel_grid_w}×{cfg.pixel_grid_h}.")

    # Chia dải cột THEO PHẠM VI Ô THẬT của ảnh (không theo grid).
    base_progress = cfg.pixel_progress_path or pp._default_progress_path()
    dummy_plan = pp.PixelPlan(
        cells=[], grid_w=cfg.pixel_grid_w, grid_h=cfg.pixel_grid_h,
        progress_path=base_progress,
    )
    x_min = min((c.x for c in cells_all), default=0)
    x_max = max((c.x for c in cells_all), default=cfg.pixel_grid_w - 1)
    log(f"[Multi] Phạm vi ô thật: cột {x_min}..{x_max} "
        f"({x_max - x_min + 1} cột) → chia cho {n} acc.")
    bounds = pp.split_columns_for_accounts(
        dummy_plan, n, base_progress, x_min=x_min, x_max=x_max)
    log("[Multi] Phân vùng cột:")
    for i, (x0, x1, ppath) in enumerate(bounds):
        log(f"  Acc{i + 1} ({accounts[i][0]}): cột {x0}-{x1} -> {ppath}")

    # Serialize cells + cfg.
    cells_serialized = [[c.x, c.y, list(c.rgb)] for c in cells_all]
    cfg_dict = dataclasses.asdict(cfg)
    base_dir = app_dir()
    stop_file = _STOP_FILE

    # Chế độ đóng gói (PyInstaller frozen): gọi chính exe với cờ --worker.
    # Chế độ dev (python): gọi "python worker_cli.py <cfg>".
    frozen = getattr(sys, "frozen", False)
    if frozen:
        exe_path = sys.executable
        cmd_prefix = [exe_path, "--worker"]
    else:
        worker_cli = os.path.join(base_dir, "worker_cli.py")
        cmd_prefix = [sys.executable, worker_cli]

    # Tạo file config JSON cho mỗi acc rồi khởi động subprocess.
    procs: list = []  # list[(acc_index, Popen, config_file)]
    for i in range(n):
        username, password = accounts[i]
        x0, x1, ppath = bounds[i]
        config_file = os.path.join(base_dir, f".multi_acc{i + 1}_cfg.json")
        acc_cfg = {
            "cfg": cfg_dict,
            "session_base": cfg.session_dir,
            "username": username,
            "password": password,
            "acc_index": i,
            "n_accounts": n,
            "cells": cells_serialized,
            "grid_w": cfg.pixel_grid_w,
            "grid_h": cfg.pixel_grid_h,
            "x_start": x0,
            "x_end": x1,
            "progress_path": ppath,
            "stop_file": stop_file,
        }
        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(acc_cfg, f)
        # Cất(chừa) 3s giữa các lần mở Chrome cho ổn định (tránh 2 login cùng lúc
        # bị web rate-limit / block).
        time.sleep(3.0)
        p = subprocess.Popen(
            cmd_prefix + [config_file],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
            bufsize=1,  # line-buffered: đọc log realtime
            cwd=base_dir,
        )
        procs.append((i, p, config_file))
        log(f"[Multi] ▶ Đã khởi động Acc{i + 1} (PID {p.pid}).")

    # Vòng lặp cha: đọc log realtime từ mỗi subprocess, chờ tất cả xong hoặc ESC.
    import threading

    def _reader(acc_idx: int, p: subprocess.Popen, out_log):
        """Đọc từng dòng stdout của subprocess -> đẩy về log GUI."""
        try:
            for line in p.stdout:
                line = line.rstrip("\n")
                if line:
                    out_log(line)
        except Exception:
            pass

    # Khởi động thread đọc log cho mỗi subprocess.
    readers: list = []
    for acc_idx, p, _cfg_file in procs:
        t = threading.Thread(target=_reader, args=(acc_idx, p, log), daemon=True)
        t.start()
        readers.append(t)

    # Chờ tất cả subprocess thoát (hoặc ESC).
    try:
        while True:
            # Kiểm tra ESC -> đặt cờ stop (subprocess đọc file flag để dừng).
            try:
                import screen_painter as sp
                if sp.is_stopped():
                    _set_stop_file(True)
            except Exception:
                pass
            # Tất cả đã xong?
            if all(p.poll() is not None for _, p, _ in procs):
                break
            time.sleep(0.3)
    except KeyboardInterrupt:
        _set_stop_file(True)
        try:
            import screen_painter as sp
            sp.request_stop()
        except Exception:
            pass

    # Chờ các thread đọc log xong (đọc nốt log cuối).
    for t in readers:
        t.join(timeout=5)
    # Chờ subprocess thoát hẳn + dọn file config tạm.
    for acc_idx, p, cfg_file in procs:
        try:
            p.wait(timeout=15)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass
        try:
            os.remove(cfg_file)
        except Exception:
            pass

    _set_stop_file(False)
    log(f"[Multi] 🏁 Xong. {n} acc đã chạy song song.")
    return {}

    _set_stop_file(False)
    total_drawn = sum(results.values())
    log(f"[Multi] 🏁 Xong. {n} acc đã chạy song song.")
    return results


if __name__ == "__main__":
    import config as cfgmod
    cfg = cfgmod.load()
    run_multi_account(cfg, log=print)
