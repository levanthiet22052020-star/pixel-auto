"""Multi-account Pixel Painter.

Mở nhiều tài khoản datn.unifolio.io.vn cùng lúc, mỗi acc vẽ một dải cột (x)
của CÙNG một bức tranh → chạy song song, vượt quota 120 ô/5 phút của 1 acc.

Workflow:
  1. python multi_painter.py setup acc1 --config accounts.yaml
     (mở Chrome, tự đăng nhập datn bằng tay, đóng Chrome để lưu phiên)
  2. python multi_painter.py paint --config accounts.yaml [--auto-split] [--reset]

Xem accounts.yaml để cấu hình.
"""
from __future__ import annotations

import argparse
import os
import sys
import threading
import time
import traceback
from dataclasses import dataclass
from typing import Optional

import yaml

import browser as br
import dom_painter as dp
import pixel_painter as pp
from config import Config


# ===========================================================================
# Đọc config nhiều acc từ accounts.yaml
# ===========================================================================
@dataclass
class Account:
    name: str
    session_dir: str
    username: str
    password: str
    proxy: str
    x_start: Optional[int]
    x_end: Optional[int]


@dataclass
class MultiConfig:
    image: str
    grid_w: int
    grid_h: int
    progress_dir: str
    headless: bool
    auto_repair: bool
    palette_path: str
    dither: bool
    bg_skip: bool
    smart_skip: bool
    color_tolerance: int
    cooldown_seconds: float
    jitter_seconds: float
    batch_size: int
    pixel_site_url: str
    pixel_url: str
    accounts: list


def _parse_grid(s: str) -> tuple[int, int]:
    """'100x100' -> (100, 100)."""
    parts = s.lower().split("x")
    if len(parts) != 2:
        raise ValueError(f"Grid sai định dạng '{s}', vd '100x100'")
    return int(parts[0]), int(parts[1])


def load_multi_config(path: str) -> MultiConfig:
    if not os.path.exists(path):
        raise FileNotFoundError(f"Không thấy file config: {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    gw, gh = _parse_grid(str(data.get("grid", "100x100")))
    accts_raw = data.get("accounts", []) or []
    accounts = []
    for a in accts_raw:
        accounts.append(Account(
            name=a.get("name", f"acc{len(accounts) + 1}"),
            session_dir=a.get("session_dir", f"session/acc{len(accounts) + 1}"),
            username=a.get("username", "") or "",
            password=a.get("password", "") or "",
            proxy=a.get("proxy", "") or "",
            x_start=a.get("x_start"),
            x_end=a.get("x_end"),
        ))
    if not accounts:
        raise ValueError("Không có account nào trong config.")

    return MultiConfig(
        image=data.get("image", ""),
        grid_w=gw,
        grid_h=gh,
        progress_dir=data.get("progress_dir", "progress_multi/"),
        headless=bool(data.get("headless", False)),
        auto_repair=bool(data.get("auto_repair", False)),
        palette_path=data.get("palette", "") or "",
        dither=bool(data.get("dither", False)),
        bg_skip=bool(data.get("bg_skip", False)),
        smart_skip=bool(data.get("smart_skip", True)),
        color_tolerance=int(data.get("color_tolerance", 24)),
        cooldown_seconds=float(data.get("cooldown_seconds", 0.0)),
        jitter_seconds=float(data.get("jitter_seconds", 0.2)),
        batch_size=int(data.get("batch_size", 0)),
        pixel_site_url=data.get("pixel_site_url", "https://datn.unifolio.io.vn"),
        pixel_url=data.get("pixel_url", "https://datn.unifolio.io.vn/pixel"),
        accounts=accounts,
    )


def auto_split_columns(accounts: list, grid_w: int, log=print) -> None:
    """Tự chia đều grid_w cột cho N acc. Gán x_start/x_end in-place."""
    n = len(accounts)
    if n == 0:
        return
    base = grid_w // n
    extra = grid_w % n
    cur = 0
    for i, acc in enumerate(accounts):
        w = base + (1 if i < extra else 0)
        acc.x_start = cur
        acc.x_end = cur + w - 1
        cur += w
    log(f"[Split] {n} acc × {grid_w} cột → " +
        ", ".join(f"{a.name}:{a.x_start}-{a.x_end}" for a in accounts))


# ===========================================================================
# Worker: 1 thread cho 1 acc
# ===========================================================================
class WorkerState:
    """Trạng thái runtime của 1 worker (cho log tổng)."""

    def __init__(self, name: str):
        self.name = name
        self.status = "init"        # init/running/login/done/error/stopped
        self.placed = 0
        self.total = 0
        self.last_msg = ""

    def __repr__(self):
        pct = (100.0 * self.placed / self.total) if self.total else 0
        return f"[{self.name}] {self.placed}/{self.total} ({pct:.0f}%) {self.last_msg}"


def run_worker(
    acc: Account,
    mc: MultiConfig,
    master_plan: pp.PixelPlan,
    state: WorkerState,
    progress_dir: str,
    log_lock: threading.Lock,
) -> None:
    """Chạy 1 acc: login datn → vào /pixel → paint_dom trên dải cột của acc."""
    prefix = f"[{acc.name}]"

    def log(msg: str):
        with log_lock:
            print(f"{prefix} {msg}", flush=True)

    try:
        # 1) Cắt plan con theo dải cột của acc.
        if acc.x_start is None or acc.x_end is None:
            state.status = "error"
            state.last_msg = "thiếu x_start/x_end"
            log(f"❌ Thiếu x_start/x_end. Dùng --auto-split hoặc điền tay trong config.")
            return
        sub_plan = pp.slice_plan_by_x(master_plan, acc.x_start, acc.x_end, "")
        os.makedirs(progress_dir, exist_ok=True)
        progress_path = os.path.join(progress_dir, f"{acc.name}.json")

        # 2) Resume nếu có.
        cfg = _build_cfg(mc, acc)
        loaded = pp.PixelPlan.load(progress_path, cfg)
        if loaded is not None:
            # Khớp lại dải cột (phòng file cũ bị lệch).
            loaded.cells = pp.filter_cells_by_x(loaded.cells, acc.x_start, acc.x_end)
            sub_plan = loaded
            log(f"📂 Resume: {sub_plan.index}/{len(sub_plan.cells)} ô trong dải cột.")
        else:
            log(f"🆕 Dải cột {acc.x_start}-{acc.x_end}: {len(sub_plan.cells)} ô cần vẽ.")

        sub_plan.progress_path = progress_path
        state.total = len(sub_plan.cells)
        state.placed = sub_plan.index

        if not sub_plan.has_more():
            state.status = "done"
            state.last_msg = "dải cột đã xong"
            log("✅ Dải cột đã vẽ xong từ trước.")
            return

        # 3) Khởi động browser riêng cho acc.
        state.status = "login"
        state.last_msg = "mở browser"
        log(f"🌐 Mở browser (session={acc.session_dir}, proxy={'có' if acc.proxy else 'không'})")
        mgr = br.BrowserManager(acc.session_dir, headless=mc.headless, proxy=acc.proxy or None)
        mgr.start()
        try:
            page = mgr.new_page()

            # 4) Config cho dom_painter (đã build ở trên cho load/resume).
            cfg = _build_cfg(mc, acc)

            # 5) Login datn + vào /pixel.
            ok = dp.login_and_open_canvas(page, cfg, log)
            if not ok:
                state.status = "error"
                state.last_msg = "không vào được /pixel"
                log("❌ Không vào được trang pixel. Bỏ acc này.")
                return

            ci = dp.get_canvas_info(page)
            if ci is None:
                state.status = "error"
                state.last_msg = "không thấy canvas"
                log("❌ Không thấy canvas.")
                return

            # 6) Vẽ.
            state.status = "running"
            state.last_msg = "đang vẽ"

            def on_progress(idx: int, total: int):
                state.placed = idx
                state.total = total
                state.last_msg = "đang vẽ"

            drawn = dp.paint_dom(
                page, cfg, sub_plan, ci, palette=[],
                log=log, batch_size=mc.batch_size, on_progress=on_progress,
            )
            state.placed = sub_plan.index
            state.total = len(sub_plan.cells)
            if sub_plan.has_more():
                state.status = "stopped"
                state.last_msg = f"dừng, còn {sub_plan.remaining()} ô"
                log(f"⏹ Dừng: đã vẽ {drawn} ô đợt này, còn {sub_plan.remaining()} ô.")
            else:
                state.status = "done"
                state.last_msg = "xong"
                log(f"🎉 XONG dải cột! Đã vẽ {sub_plan.index} ô.")
        finally:
            try:
                mgr.close()
            except Exception:
                pass

    except Exception as e:
        state.status = "error"
        state.last_msg = f"lỗi: {e}"
        log(f"❌ Lỗi worker: {e}")
        log(traceback.format_exc())


def _build_cfg(mc: MultiConfig, acc: Account) -> Config:
    """Tạo object Config từ MultiConfig + acc để dom_painter dùng."""
    cfg = Config()
    cfg.pixel_image_path = mc.image
    cfg.pixel_grid_w = mc.grid_w
    cfg.pixel_grid_h = mc.grid_h
    cfg.pixel_site_url = mc.pixel_site_url
    cfg.pixel_url = mc.pixel_url
    cfg.pixel_username = acc.username
    cfg.pixel_password = acc.password
    cfg.pixel_palette_path = mc.palette_path
    cfg.pixel_dither = mc.dither
    cfg.pixel_bg_skip = mc.bg_skip
    cfg.pixel_smart_skip = mc.smart_skip
    cfg.pixel_color_tolerance = mc.color_tolerance
    cfg.pixel_cooldown_seconds = mc.cooldown_seconds
    cfg.pixel_jitter_seconds = mc.jitter_seconds
    cfg.pixel_batch_size = mc.batch_size
    return cfg


# ===========================================================================
# Orchestrator: chạy nhiều worker song song
# ===========================================================================
def paint_all(mc: MultiConfig, reset: bool = False, only: Optional[str] = None,
              dry_run: bool = False) -> int:
    log_lock = threading.Lock()

    def log(msg: str):
        with log_lock:
            print(msg, flush=True)

    accounts = mc.accounts
    if only:
        accounts = [a for a in accounts if a.name == only]
        if not accounts:
            log(f"❌ Không thấy account '{only}' trong config.")
            return 1

    # Auto-split nếu có acc thiếu x_start/x_end.
    if any(a.x_start is None or a.x_end is None for a in accounts):
        auto_split_columns(accounts, mc.grid_w, log)

    # Reset progress nếu yêu cầu.
    if reset:
        for a in accounts:
            p = os.path.join(mc.progress_dir, f"{a.name}.json")
            if os.path.exists(p):
                os.remove(p)
                log(f"🗑 Đã xoá progress {p}")

    # Build master plan 1 lần (dùng cho mọi acc).
    log("=" * 60)
    log(f"🖼 Load ảnh: {mc.image} (lưới {mc.grid_w}×{mc.grid_h})")
    if not os.path.exists(mc.image):
        log(f"❌ Không thấy ảnh: {mc.image}")
        return 1
    cfg_tmp = _build_cfg(mc, accounts[0])
    palette = pp.build_palette(cfg_tmp)
    master_plan = pp.PixelPlan.from_image(cfg_tmp, palette)
    log(f"📊 Master plan: {len(master_plan.cells)} ô.")

    if dry_run:
        log("=" * 60)
        log("🔍 DRY-RUN — không vẽ thật, chỉ kiểm tra chia cột:")
        for a in accounts:
            sub = pp.filter_cells_by_x(master_plan.cells, a.x_start, a.x_end)
            log(f"  • {a.name}: cột {a.x_start}-{a.x_end} = {len(sub)} ô "
                f"(proxy={'có' if a.proxy else 'không'})")
        log("=" * 60)
        return 0

    log(f"🚀 Bắt đầu {len(accounts)} acc song song. Ctrl+C để dừng tất cả.")
    log("=" * 60)

    states = [WorkerState(a.name) for a in accounts]
    threads = []
    for acc, st in zip(accounts, states):
        t = threading.Thread(
            target=run_worker,
            args=(acc, mc, master_plan, st, mc.progress_dir, log_lock),
            daemon=True,
            name=f"worker-{acc.name}",
        )
        threads.append(t)
        t.start()

    # Monitor thread: log tổng tiến độ mỗi 5s.
    stop_monitor = threading.Event()

    def monitor():
        while not stop_monitor.wait(5.0):
            with log_lock:
                line = " | ".join(str(s) for s in states)
                print(f"\n📊 TIẾN ĐỘ: {line}\n", flush=True)

    mon_t = threading.Thread(target=monitor, daemon=True)
    mon_t.start()

    # Chờ tất cả worker xong hoặc Ctrl+C.
    try:
        for t in threads:
            t.join()
    except KeyboardInterrupt:
        log("\n⏹ Ctrl+C — đang dừng các worker...")

    stop_monitor.set()

    log("=" * 60)
    log("📋 KẾT QUẢ:")
    for st in states:
        log(f"  {st}")
    errs = sum(1 for s in states if s.status == "error")
    log("=" * 60)
    return 1 if errs else 0


# ===========================================================================
# Setup: login lần đầu cho 1 acc
# ===========================================================================
def setup_account(mc: MultiConfig, name: str) -> int:
    acc = next((a for a in mc.accounts if a.name == name), None)
    if acc is None:
        print(f"❌ Không thấy account '{name}'. Các acc: "
              f"{[a.name for a in mc.accounts]}")
        return 1
    print(f"🔑 Setup login cho {acc.name} (session={acc.session_dir})")
    print("   Mở Chrome → tự đăng nhập datn.unifolio.io.vn → ĐÓNG Chrome để lưu.")
    cfg = _build_cfg(mc, acc)
    site = cfg.pixel_site_url.rstrip("/")
    mgr = br.BrowserManager(acc.session_dir, headless=False, proxy=acc.proxy or None)
    mgr.start()
    page = mgr.new_page()
    page.goto(site, wait_until="domcontentloaded", timeout=60000)
    try:
        while mgr.context.pages:
            page.wait_for_timeout(1000)
    except Exception:
        pass
    mgr.close()
    print(f"✅ Đã lưu phiên cho {acc.name}.")
    return 0


# ===========================================================================
# CLI
# ===========================================================================
def main():
    parser = argparse.ArgumentParser(
        description="Multi-account Pixel Painter — nhiều acc vẽ song song.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ví dụ:
  python multi_painter.py setup acc1 --config accounts.yaml
  python multi_painter.py paint --config accounts.yaml --auto-split
  python multi_painter.py paint --config accounts.yaml --account acc1 --dry-run
  python multi_painter.py paint --config accounts.yaml --reset
""",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_setup = sub.add_parser("setup", help="Login lần đầu cho 1 acc (mở Chrome).")
    p_setup.add_argument("name", help="Tên acc trong config (vd acc1)")
    p_setup.add_argument("--config", default="accounts.yaml")

    p_paint = sub.add_parser("paint", help="Vẽ song song nhiều acc.")
    p_paint.add_argument("--config", default="accounts.yaml")
    p_paint.add_argument("--auto-split", action="store_true",
                         help="Tự chia đều grid_w cột cho N acc.")
    p_paint.add_argument("--reset", action="store_true",
                         help="Xoá progress tất cả acc (vẽ lại từ đầu).")
    p_paint.add_argument("--account", default=None,
                         help="Chỉ chạy 1 acc (debug).")
    p_paint.add_argument("--dry-run", action="store_true",
                         help="Không vẽ thật, chỉ kiểm tra chia cột + load ảnh.")

    args = parser.parse_args()

    mc = load_multi_config(args.config)

    if args.cmd == "setup":
        sys.exit(setup_account(mc, args.name))
    elif args.cmd == "paint":
        # auto-split flag ưu tiên hơn cả khi config thiếu x_start/x_end.
        if args.auto_split:
            auto_split_columns(mc.accounts, mc.grid_w, print)
        sys.exit(paint_all(mc, reset=args.reset, only=args.account,
                           dry_run=args.dry_run))


if __name__ == "__main__":
    main()
