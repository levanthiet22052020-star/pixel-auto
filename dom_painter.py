"""DOM Painter — tô tranh pixel trên canvas HTML5 của trang datn.unifolio.io.vn.

ĐÃ TEST THẬT trên site (2026-07-29), kết luận:
  • Login tại /login hoặc /app (session Playwright giữ persistent).
  • Dashboard /app: link "Vẽ Pixel" (a[href="/pixel"]) → /pixel.
  • Trang /pixel:
      - Canvas chính HTML5 <canvas width=2304 height=1440> = lưới 384×240 ô.
        Mỗi ô = 6×6 px (canvas-space). Hiển thị scale theo cửa sổ.
      - Còn 1 canvas minimap 384×240 ở góc (bỏ qua, lấy canvas lớn nhất).
      - Chọn màu: <input type="color"> ẩn trong "Chọn màu tùy chỉnh".
        -> Set input.value = "#RRGGBB" + dispatch input/change → đổi màu CHÍNH XÁC,
           không cần quantize về 23 swatch.
      - Công cụ: button[aria-label="Bút"] (mặc định đã chọn).
  • Vẽ: page.mouse.move(x,y) → page.mouse.down() → page.mouse.up() trên canvas.
    KHÔNG dùng page.mouse.click() (canvas React bắt pointerdown, click bị bỏ qua).
  • Đọc canvas: ctx.getImageData toàn bộ (2304×1440) chỉ ~8ms → smart skip rẻ.
  • Rate limit: 120 ô / 5 phút (cửa sổ trượt). Vượt quá → server SILENT REJECT
    (ô không đổi màu, không có toast). Tool PHẢI verify sau khi vẽ + retry.
  • Anti-focus: tab mất focus → overlay "Nội dung đang được bảo vệ".
    Nhưng Playwright tự giữ focus nên không ảnh hưởng.
"""
from __future__ import annotations

import os
import random
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

import pixel_painter as pp
from config import Config


# ===========================================================================
# Cờ dừng dùng chung giữa các process (multi-account).
# Process con không chia memory -> ghi file tạm, dom_painter đọc để nhận ESC.
# ===========================================================================
def _stop_flag_path() -> str:
    try:
        from config import app_dir
        return os.path.join(app_dir(), ".multi_stop_flag")
    except Exception:
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), ".multi_stop_flag")


_MULTI_STOP_FILE = _stop_flag_path()


def _is_multi_stopped() -> bool:
    """Đọc cờ dừng từ file (đặt bởi multi_account khi ESC)."""
    try:
        return os.path.exists(_MULTI_STOP_FILE)
    except Exception:
        return False


def _should_stop() -> bool:
    """Gộp: dừng nếu screen_painter flag HOẶC file multi-account flag."""
    try:
        from screen_painter import is_stopped
        if is_stopped():
            return True
    except Exception:
        pass
    return _is_multi_stopped()


# ===========================================================================
# Selectors chính xác (đã verify trên site thật)
# ===========================================================================
CANVAS_JS = "Array.from(document.querySelectorAll('canvas')).find(c => c.width > 1000)"

# Input chọn màu tùy chỉnh (type=color, ẩn, opacity:0).
COLOR_INPUT_SELECTOR = '[aria-label="Bảng màu Pixel"] input[type="color"]'

# Nút công cụ Bút.
PEN_BTN = 'button[aria-label="Bút"]'

# Selectors đăng nhập.
USERNAME_SELECTOR = "input[placeholder*='Ví dụ' i], input[placeholder*='MSSV' i], input[name*='user' i]"
PASSWORD_SELECTOR = "input[type='password'], input[placeholder*='mật khẩu' i]"
LOGIN_BTN_SELECTOR = "button:has-text('Đăng nhập')"

# Link "Vẽ Pixel" trên dashboard.
DRAW_LINK_SELECTOR = "a:has-text('Vẽ Pixel'), a[href*='/pixel']"

# Grid canvas thật (verify).
GRID_W, GRID_H = 384, 240


@dataclass
class CanvasInfo:
    """Thông tin canvas để tính tọa độ click."""
    rect_x: float
    rect_y: float
    rect_w: float
    rect_h: float
    canvas_w: int
    canvas_h: int
    cell_px_x: float
    cell_px_y: float
    # Grid thật của canvas (auto-detect, không hardcode). Trước đây site dùng
    # 384×240, nay đổi sang 512×320 (cell 4px) → phải đo động để click đúng.
    grid_w: int = GRID_W
    grid_h: int = GRID_H

    def cell_to_page(self, gx: int, gy: int) -> tuple[float, float]:
        """Chuyển ô (gx,gy) sang toạ độ click trên trang (tâm ô)."""
        cx = (gx + 0.5) * self.cell_px_x
        cy = (gy + 0.5) * self.cell_px_y
        sx = cx / self.canvas_w * self.rect_w
        sy = cy / self.canvas_h * self.rect_h
        return (self.rect_x + sx, self.rect_y + sy)

    def cell_rect_on_page(self, gx: int, gy: int) -> tuple[float, float, float, float]:
        """Trả về (x, y, w, h) hình chữ nhật ô (gx,gy) trên trang (pixel màn hình)."""
        sx0 = gx * self.cell_px_x / self.canvas_w * self.rect_w
        sy0 = gy * self.cell_px_y / self.canvas_h * self.rect_h
        sw = self.cell_px_x / self.canvas_w * self.rect_w
        sh = self.cell_px_y / self.canvas_h * self.rect_h
        return (self.rect_x + sx0, self.rect_y + sy0, sw, sh)


# ===========================================================================
# Overlay: phủ ảnh gốc lên canvas (bán trong suốt) để xem ảnh tham chiếu khi vẽ
# ===========================================================================
_OVERLAY_IMG_ID = "__pixel_overlay_img__"


def show_image_overlay(
    page, ci: CanvasInfo, cfg: Config, log: Callable[[str], None] = print
) -> bool:
    """Phủ ảnh gốc (pixel_painter.pixel_image_path) lên trên canvas trên trang.

    Ảnh được resize đúng kích thước vùng ô ảnh trên canvas, đặt opacity theo
    cfg.pixel_overlay_opacity (0-1, 0 = tắt). Dùng trong DOM mode để xem ảnh
    tham chiếu ngay trên canvas khi đang vẽ.
    """
    opacity = float(getattr(cfg, "pixel_overlay_opacity", 0.0) or 0.0)
    if opacity <= 0:
        return False
    img_path = getattr(cfg, "pixel_image_path", "") or ""
    if not img_path or not os.path.exists(img_path):
        log("[Overlay] Không có ảnh nguồn, bỏ qua overlay.")
        return False
    # Vùng ô ảnh trên canvas (theo tọa độ ô grid).
    gw = int(getattr(cfg, "pixel_grid_w", GRID_W))
    gh = int(getattr(cfg, "pixel_grid_h", GRID_H))
    ox = int(getattr(cfg, "pixel_offset_x", 0))
    oy = int(getattr(cfg, "pixel_offset_y", 0))
    # Tính vùng pixel trên màn hình: từ ô (ox,oy) tới (ox+gw, oy+gh).
    img_x, img_y, cw, ch = ci.cell_rect_on_page(ox, oy)
    img_w = cw * gw
    img_h = ch * gh
    # Đọc ảnh → resize về gw×gh → base64 PNG (để hiển thị chính xác pixel art).
    try:
        from PIL import Image
        import base64
        import io
        im = Image.open(img_path).convert("RGB")
        im = im.resize((gw, gh), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        data_uri = f"data:image/png;base64,{b64}"
    except Exception as e:
        log(f"[Overlay] Lỗi xử lý ảnh: {e}")
        return False
    # Inject <img> tuyệt đối lên trên canvas.
    js = """
    ([id, src, x, y, w, h, op]) => {
        let img = document.getElementById(id);
        if (!img) {
            img = document.createElement('img');
            img.id = id;
            img.style.position = 'absolute';
            img.style.pointerEvents = 'none';
            img.style.zIndex = '999999';
            img.style.imageRendering = 'pixelated';
            document.body.appendChild(img);
        }
        img.src = src;
        img.style.left = x + 'px';
        img.style.top = y + 'px';
        img.style.width = w + 'px';
        img.style.height = h + 'px';
        img.style.opacity = String(op);
        return true;
    }
    """
    try:
        page.evaluate(js, [_OVERLAY_IMG_ID, data_uri, img_x, img_y, img_w, img_h, opacity])
        log(f"[Overlay] ✅ Đã phủ ảnh gốc lên canvas (opacity {opacity:.0%}, "
            f"vùng {img_w:.0f}×{img_h:.0f}px).")
        return True
    except Exception as e:
        log(f"[Overlay] Lỗi inject ảnh: {e}")
        return False


def hide_image_overlay(page) -> None:
    """Gỡ ảnh overlay khỏi trang."""
    try:
        page.evaluate(
            """(id) => {
                const img = document.getElementById(id);
                if (img) img.remove();
            }""",
            _OVERLAY_IMG_ID,
        )
    except Exception:
        pass


def refresh_image_overlay(page, ci: CanvasInfo, cfg: Config) -> None:
    """Cập nhật lại vị trí overlay khi cuộn/resize (gọi định kỳ)."""
    opacity = float(getattr(cfg, "pixel_overlay_opacity", 0.0) or 0.0)
    if opacity <= 0:
        return
    try:
        gw = int(getattr(cfg, "pixel_grid_w", GRID_W))
        gh = int(getattr(cfg, "pixel_grid_h", GRID_H))
        ox = int(getattr(cfg, "pixel_offset_x", 0))
        oy = int(getattr(cfg, "pixel_offset_y", 0))
        img_x, img_y, cw, ch = ci.cell_rect_on_page(ox, oy)
        img_w = cw * gw
        img_h = ch * gh
        page.evaluate(
            """([id, x, y, w, h]) => {
                const img = document.getElementById(id);
                if (img) {
                    img.style.left = x + 'px';
                    img.style.top = y + 'px';
                    img.style.width = w + 'px';
                    img.style.height = h + 'px';
                }
            }""",
            [_OVERLAY_IMG_ID, img_x, img_y, img_w, img_h],
        )
    except Exception:
        pass


# ===========================================================================
# Đăng nhập + vào trang pixel
# ===========================================================================
def login_and_open_canvas(page, cfg: Config, log: Callable[[str], None] = print) -> bool:
    """Đăng nhập trang chính rồi bấm 'Vẽ Pixel' để vào trang canvas."""
    site = (cfg.pixel_site_url or "https://datn.unifolio.io.vn").rstrip("/")
    log(f"[DOM] Mở trang chính: {site}")
    try:
        page.goto(site, wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        log(f"[DOM][Lỗi] không mở được trang (lần 1): {e}")
        # Có thể do cookie/session cũ gây redirect loop → clear rồi vào lại.
        try:
            page.context.clear_cookies()
            log("[DOM] Đã xóa cookie, mở lại trang...")
            page.wait_for_timeout(800)
            page.goto(site, wait_until="domcontentloaded", timeout=60000)
        except Exception as e2:
            log(f"[DOM][Lỗi] không mở được trang (lần 2): {e2}")
            return False
    page.wait_for_timeout(2500)

    # Clear cookie + reload 1 lần nữa để chắc chắn trạng thái sạch (tránh redirect loop
    # do cookie hỏng từ phiên cũ). Giữ URL gốc (kèm query string nếu có).
    try:
        page.context.clear_cookies()
        log("[DOM] Clear cookie + reload trang để login sạch.")
        page.reload(wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2000)
    except Exception as e:
        log(f"[DOM][Cảnh báo] clear/reload lỗi ({e}), tiếp tục.")

    # Nếu có form đăng nhập → điền thông tin.
    if "/login" in page.url or page.query_selector(PASSWORD_SELECTOR):
        if cfg.pixel_username and cfg.pixel_password:
            log(f"[DOM] Đăng nhập với {cfg.pixel_username}...")
            _do_login(page, cfg.pixel_username, cfg.pixel_password, log)
            page.wait_for_timeout(3000)
        else:
            log("[DOM] Có form đăng nhập nhưng chưa nhập tài khoản trong config.")

    # Nếu chưa ở /pixel → bấm link "Vẽ Pixel" hoặc vào thẳng URL.
    if "/pixel" not in page.url:
        log("[DOM] Tìm link 'Vẽ Pixel'...")
        link = page.query_selector(DRAW_LINK_SELECTOR)
        if link:
            link.click()
            log("[DOM] Đã bấm 'Vẽ Pixel'.")
            page.wait_for_timeout(3000)
        else:
            # Fallback: vào thẳng URL.
            pixel_url = (cfg.pixel_url or site + "/pixel").rstrip("/")
            log(f"[DOM] Không thấy link, vào thẳng {pixel_url}")
            try:
                page.goto(pixel_url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(3000)
            except Exception as e:
                log(f"[DOM][Lỗi] goto /pixel: {e}")

    # Sau khi vào /pixel, nếu bị redirect về /login (chưa đăng nhập) → login rồi quay lại.
    # Vòng lặp này tránh tình trạng /pixel -> /login -> /pixel -> /login ... không dừng.
    for attempt in range(3):
        needs_login = ("/login" in page.url) or bool(page.query_selector(PASSWORD_SELECTOR))
        if not needs_login:
            break
        if not (cfg.pixel_username and cfg.pixel_password):
            log("[DOM] Có form đăng nhập nhưng chưa nhập tài khoản trong config.")
            break
        log(f"[DOM] Phát hiện /login (lần {attempt + 1}/3), đăng nhập rồi vào lại /pixel...")
        _do_login(page, cfg.pixel_username, cfg.pixel_password, log)
        page.wait_for_timeout(3000)
        # Sau login, thử vào thẳng /pixel.
        pixel_url = (cfg.pixel_url or site + "/pixel").rstrip("/")
        try:
            page.goto(pixel_url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(2500)
        except Exception as e:
            log(f"[DOM][Lỗi] goto /pixel sau login: {e}")
            break

    # Xác nhận đã vào trang pixel + có canvas.
    ci = get_canvas_info(page)
    if ci is not None:
        log(f"[DOM] ✅ Đã vào trang pixel. Canvas {ci.canvas_w}×{ci.canvas_h} "
            f"(hiển thị {ci.rect_w:.0f}×{ci.rect_h:.0f}px).")
        return True

    # Chưa thấy canvas → chờ người dùng tự xử lý (Chrome vẫn mở).
    log("=" * 60)
    log("[DOM] ⏸ Chưa thấy canvas tự động.")
    log("[DOM] Chrome vẫn mở. Bạn tự xử lý trong Chrome:")
    log("[DOM]   • Đăng nhập nếu chưa")
    log("[DOM]   • Bấm 'Vẽ Pixel' để vào trang canvas")
    log("[DOM] Tool tự dò lại mỗi 3 giây. Thấy canvas -> tự tô. ESC để hủy.")
    log("=" * 60)
    start = time.time()
    while time.time() - start < 600:
        if _should_stop():
            log("[DOM] Đã hủy theo ESC.")
            return False
        page.wait_for_timeout(3000)
        ci = get_canvas_info(page)
        if ci is not None:
            log("[DOM] ✅ Thấy canvas! Bắt đầu.")
            return True
    log("[DOM] Hết 10 phút chờ.")
    return False


def _do_login(page, username: str, password: str, log) -> bool:
    u = page.query_selector(USERNAME_SELECTOR)
    p = page.query_selector(PASSWORD_SELECTOR)
    if not u or not p:
        log("[DOM][Login] Không thấy ô user/password.")
        return False
    try:
        u.fill("")
        u.type(username, delay=20)
        p.fill("")
        p.type(password, delay=20)
        page.wait_for_timeout(300)
        btn = page.query_selector(LOGIN_BTN_SELECTOR)
        if btn:
            btn.click()
        else:
            page.keyboard.press("Enter")
        log("[DOM][Login] Đã gửi đăng nhập.")
        return True
    except Exception as e:
        log(f"[DOM][Login] lỗi: {e}")
        return False


# ===========================================================================
# Canvas HTML5
# ===========================================================================
def detect_grid_size(page, canvas_w: int, canvas_h: int,
                     log: Callable[[str], None] = lambda m: None) -> tuple[int, int]:
    """Auto-detect grid thật (grid_w, grid_h) của canvas bằng auto-correlation.

    Site từng dùng 384×240 (cell 6px), nay đổi sang 512×320 (cell 4px). Hardcode
    sẽ click/đọc lệch → phải đo động. Phương pháp: lấy vài dòng pixel, với mỗi
    cell_size ứng viên, đếm pixel[x] ≈ pixel[x+step].

    Cell THẬT cho ratio CAO NHẤT (vì pixel trong 1 ô đồng nhất → pixel[x] và
    pixel[x+cell] cùng ô, giống nhau hoàn toàn). Các bội của cell (2cell, 3cell...)
    cũng ratio cao nhưng THẤP HƠN cell thật một chút (ranh giới ô xen vào giữa).
    → Chọn step có ratio cao NHẤT tuyệt đối = cell thật. KHÔNG chọn step lớn nhất
    (bug cũ: chọn 16 thay vì 4 → click lệch, verify FAIL → tưởng rate-limit).
    """
    # Ưu tiên các cell size phổ biến của pixel canvas, từ nhỏ đến lớn.
    candidates = [4, 6, 8, 3, 5, 10, 12, 16]
    try:
        data = page.evaluate(
            """([nRows]) => {
                const c = Array.from(document.querySelectorAll('canvas'))
                    .sort((a,b)=>(b.width*b.height)-(a.width*a.height))[0];
                if (!c) return null;
                const ctx = c.getContext('2d');
                const W = c.width, H = c.height;
                const rows = [];
                for (let i = 0; i < nRows; i++) {
                    const y = Math.floor((i + 0.5) * H / nRows);
                    const img = ctx.getImageData(0, y, W, 1).data;
                    const row = [];
                    for (let x = 0; x < W; x++) row.push([img[x*4],img[x*4+1],img[x*4+2]]);
                    rows.push(row);
                }
                return {W, H, rows};
            }""",
            [8],
        )
        if not data or not data.get("rows"):
            return GRID_W, GRID_H
        W, rows = data["W"], data["rows"]
        tol = 30
        results = []
        for step in candidates:
            matches = total = 0
            for row in rows:
                for x in range(W - step):
                    a, b = row[x], row[x + step]
                    if abs(a[0]-b[0]) <= tol and abs(a[1]-b[1]) <= tol and abs(a[2]-b[2]) <= tol:
                        matches += 1
                    total += 1
            ratio = matches / total if total else 0
            results.append((step, ratio))
        # Cell thật = step có ratio cao nhất tuyệt đối.
        results.sort(key=lambda r: -r[1])
        best_step, best_ratio = results[0]
        # Ngưỡng tối thiểu: nếu ratio cao nhất < 0.6 → canvas gần như đồng màu
        # (trống) → không detect được, dùng mặc định.
        if best_ratio < 0.6:
            log(f"[DOM] Auto-detect: canvas quá đồng màu (ratio cao nhất {best_ratio:.2f} "
                f"< 0.6) → dùng mặc định {GRID_W}×{GRID_H}.")
            return GRID_W, GRID_H
        gw = canvas_w // best_step
        gh = canvas_h // best_step
        log(f"[DOM] Auto-detect grid: cell={best_step}px (ratio {best_ratio:.2f}, cao nhất) "
            f"→ grid {gw}×{gh}. Tất cả: {[(s, round(r,2)) for s, r in results]}.")
        return gw, gh
    except Exception as e:
        log(f"[DOM][Cảnh báo] detect_grid_size lỗi ({e}), dùng mặc định {GRID_W}×{GRID_H}.")
        return GRID_W, GRID_H


def get_canvas_info(page, log: Callable[[str], None] = lambda m: None) -> Optional[CanvasInfo]:
    """Lấy thông tin canvas chính (lớn nhất) + auto-detect grid. None nếu không có."""
    try:
        data = page.evaluate(
            """() => {
                const cs = Array.from(document.querySelectorAll('canvas'));
                const c = cs.sort((a,b)=>(b.width*b.height)-(a.width*a.height))[0];
                if (!c || c.width < 1000) return null;
                const r = c.getBoundingClientRect();
                return {
                    rect_x: r.x, rect_y: r.y, rect_w: r.width, rect_h: r.height,
                    canvas_w: c.width, canvas_h: c.height
                };
            }"""
        )
        if not data:
            return None
        cw, ch = data["canvas_w"], data["canvas_h"]
        # Auto-detect grid thật (site đổi kích thước canvas → grid đổi theo).
        gw, gh = detect_grid_size(page, cw, ch, log)
        return CanvasInfo(
            rect_x=data["rect_x"], rect_y=data["rect_y"],
            rect_w=data["rect_w"], rect_h=data["rect_h"],
            canvas_w=cw, canvas_h=ch,
            cell_px_x=cw / float(gw),
            cell_px_y=ch / float(gh),
            grid_w=gw, grid_h=gh,
        )
    except Exception as e:
        log(f"[DOM][Cảnh báo] get_canvas_info lỗi: {e}")
        return None


def read_canvas_pixels(page, grid_w: int = GRID_W, grid_h: int = GRID_H) -> dict:
    """Đọc màu hiện tại của TẤT CẢ ô qua getImageData (toàn canvas 1 lần, ~8ms).

    Trả về {(x,y):(r,g,b)}.
    """
    data = page.evaluate(
        """([gw, gh]) => {
            const cs = Array.from(document.querySelectorAll('canvas'));
            const c = cs.sort((a,b)=>(b.width*b.height)-(a.width*a.height))[0];
            if (!c) return null;
            const ctx = c.getContext('2d');
            const cw = c.width / gw, chh = c.height / gh;
            const out = [];
            for (let y=0; y<gh; y++) {
                for (let x=0; x<gw; x++) {
                    const d = ctx.getImageData(Math.floor((x+0.5)*cw), Math.floor((y+0.5)*chh), 1, 1).data;
                    out.push([x, y, d[0], d[1], d[2]]);
                }
            }
            return out;
        }""",
        [grid_w, grid_h],
    )
    if not data:
        return {}
    return {(x, y): (r, g, b) for (x, y, r, g, b) in data}


def read_cells(page, cells: list, grid_w: int = GRID_W, grid_h: int = GRID_H) -> dict:
    """Đọc màu của một tập ô cụ thể (tiết kiệm hơn khi chỉ cần vài ô).

    cells: list các (x,y). Trả về {(x,y):(r,g,b)}.
    """
    if not cells:
        return {}
    data = page.evaluate(
        """([pts, gw, gh]) => {
            const cs = Array.from(document.querySelectorAll('canvas'));
            const c = cs.sort((a,b)=>(b.width*b.height)-(a.width*a.height))[0];
            if (!c) return null;
            const ctx = c.getContext('2d');
            const cw = c.width / gw, chh = c.height / gh;
            return pts.map(([x,y]) => {
                const d = ctx.getImageData(Math.floor((x+0.5)*cw), Math.floor((y+0.5)*chh), 1, 1).data;
                return [x, y, d[0], d[1], d[2]];
            });
        }""",
        [[[x, y] for (x, y) in cells], grid_w, grid_h],
    )
    if not data:
        return {}
    return {(x, y): (r, g, b) for (x, y, r, g, b) in data}


# ===========================================================================
# Chọn màu — dùng input[type=color] (chính xác tuyệt đối, không quantize)
# ===========================================================================
# Thread-local: mỗi worker (mỗi tài khoản) giữ cache màu riêng để tránh xung đột
# khi nhiều Chrome chạy song song.
_tl = threading.local()


def _get_last_color() -> Optional[str]:
    return getattr(_tl, "last_color", None)


def _set_last_color(h: Optional[str]) -> None:
    _tl.last_color = h


def set_color(page, rgb: tuple[int, int, int], log) -> bool:
    """Set màu qua input[type=color]. rgb là tuple (r,g,b) 0-255."""
    hexcode = "#%02X%02X%02X" % rgb
    if _get_last_color() == hexcode:
        return True  # đã set rồi, skip
    try:
        ok = page.evaluate(
            """([sel, hex]) => {
                const inp = document.querySelector(sel);
                if (!inp) return false;
                const setter = Object.getOwnPropertyDescriptor(
                    window.HTMLInputElement.prototype, 'value').set;
                setter.call(inp, hex);
                inp.dispatchEvent(new Event('input', {bubbles:true}));
                inp.dispatchEvent(new Event('change', {bubbles:true}));
                return inp.value.toLowerCase() === hex.toLowerCase();
            }""",
            [COLOR_INPUT_SELECTOR, hexcode],
        )
        if ok:
            _set_last_color(hexcode)
            time.sleep(0.03)  # đợi React cập nhật state (tối thiểu)
            return True
        log(f"[DOM] Set màu {hexcode} thất bại (input không nhận).")
    except Exception as e:
        log(f"[DOM][Cảnh báo] set màu {hexcode} lỗi: {e}")
    return False


def reset_color_cache():
    """Reset cache màu (gọi khi bắt đầu phiên mới)."""
    _set_last_color(None)


# Bảng màu legacy — hiện không dùng (vẽ màu tùy ý qua input[type=color]).
def read_palette(page) -> list[tuple[int, int, int]]:
    return list(pp.DEFAULT_PALETTE)


# ===========================================================================
# Vẽ 1 ô + verify + đọc cooldown
# ===========================================================================
def paint_cell(page, ci: CanvasInfo, gx: int, gy: int, humanize: bool = True) -> None:
    """Vẽ 1 ô bằng mouse.move → mouse.down → mouse.up.

    humanize=True: mô phỏng tay người — hover lệch nhẹ rồi trượt vào giữa ô,
    giữ phím chút rồi thả. Tránh pattern máy (move→down→up tức thì) mà server
    có thể dùng để flag/khóa tài khoản.
    """
    x, y = ci.cell_to_page(gx, gy)
    if humanize:
        # Hover lệch 1-2px rồi trượt vào giữa ô (người thật không click chính
        # xác pixel bao giờ).
        jx = x + random.uniform(-1.8, 1.8)
        jy = y + random.uniform(-1.8, 1.8)
        page.mouse.move(jx, jy)
        time.sleep(random.uniform(0.02, 0.08))
        page.mouse.move(x, y)
        time.sleep(random.uniform(0.01, 0.05))
    else:
        page.mouse.move(x, y)
    page.mouse.down()
    if humanize:
        # Giữ phím chút (người thật không down→up tức thì).
        time.sleep(random.uniform(0.03, 0.12))
    page.mouse.up()


def _human_delay(lo: float, hi: float) -> None:
    """Nghỉ ngẫu nhiên trong [lo, hi] giây. Dùng giữa các ô / giữa các nét vẽ."""
    if hi > lo:
        time.sleep(random.uniform(lo, hi))


def _long_break(cfg: Config, log: Callable[[str], None] = print) -> bool:
    """Với xác suất cfg.pixel_long_break_chance, nghỉ siêu dài (giống người đi
    làm việc khác). Trả True nếu đã nghỉ, False nếu không.
    """
    if random.random() < cfg.pixel_long_break_chance:
        dur = random.uniform(cfg.pixel_long_break_min, cfg.pixel_long_break_max)
        log(f"[Humanize] ☕ Nghỉ dài {dur:.1f}s (giống người xem ảnh/làm việc khác).")
        t0 = time.time()
        while time.time() - t0 < dur:
            if _should_stop():
                break
            time.sleep(1)
        return True
    return False


def patch_devtools_detection(page, log: Callable[[str], None] = print) -> None:
    """Vô hiệu hóa module 87105 (DevTools detection) của web datn.

    Web kiểm tra mỗi 1s: nếu window.outerWidth - innerWidth > 160 (do DevTools
    chiếm chỗ) → console cảnh báo đỏ "CẢNH BÁO". Mặc dù không khóa tài khoản,
    nó gây nhiễu khi debug. Hàm này override outerWidth/outerHeight để chênh lệch
    luôn nhỏ hơn ngưỡng 160px.

    Lưu ý: KHÔNG cần thiết nếu không mở DevTools khi chạy tool. Nhưng bật sẵn
    để đề phòng user mở F12 inspect.
    """
    try:
        page.add_init_script("""
            try {
                Object.defineProperty(window, 'outerWidth', {
                    get: () => window.innerWidth,
                    configurable: true
                });
                Object.defineProperty(window, 'outerHeight', {
                    get: () => window.innerHeight + 80,
                    configurable: true
                });
            } catch(e) {}
        """)
        log("[Humanize] Đã patch DevTools detection (module 87105).")
    except Exception as e:
        log(f"[Humanize] Patch DevTools detection lỗi ({e}) — bỏ qua.")


def verify_cell(page, gx: int, gy: int, expected: tuple[int, int, int],
                grid_w: int = GRID_W, grid_h: int = GRID_H,
                before: Optional[tuple[int, int, int]] = None) -> bool:
    """Kiểm tra xem ô đã được vẽ thành công chưa.

    Web datn hiện nay có bước LÀM TRÒN MÀU (quantize): set (255,0,0) → web lưu
    (212,32,39). Nếu so sánh với `expected` (màu đã set) với tolerance nhỏ → mọi
    ô đều báo FAIL nhầm thành rate-limit → tool đứng yên không tô.

    Chiến lược (chống quantize):
      1. Nếu có `before` (màu ô TRƯỚC khi vẽ): ô đổi màu đáng kể so với before
         → coi như VẼ THÀNH CÔNG (web đã nhận pixel, chỉ làm tròn màu). Đây là
         tín hiệu đáng tin nhất vì rate-limit reject thì ô KHÔNG đổi màu gì.
      2. Nếu `before` không có/khác không đáng kể: fallback so với `expected`
         với tolerance rộng (80) để dung nạp quantize của web.
    """
    res = read_cells(page, [(gx, gy)], grid_w, grid_h)
    if not res:
        return False
    r, g, b = res[(gx, gy)]
    # (1) So before vs after — tín hiệu chính: ô có thực sự đổi không.
    if before is not None:
        db = max(abs(r - before[0]), abs(g - before[1]), abs(b - before[2]))
        if db >= 25:
            # Ô đổi rõ → vẽ thành công (bất chấp web làm tròn màu).
            return True
        # before == after gần như giống hệt → KHÔNG đổi → có thể bị reject.
        # Tiếp tục kiểm tra (2) xem after có khớp expected không.
    # (2) Fallback: so với expected (màu đã set) với tolerance rộng chống quantize.
    # Đo thực tế: web lệch tới Δ=74 (màu cam). Dùng 80 để an toàn.
    er, eg, eb = expected
    return (abs(r - er) <= 80 and abs(g - eg) <= 80 and abs(b - eb) <= 80)


def read_cooldown_seconds(page) -> int:
    """Đọc số giây chờ từ toast 'Bạn có thể vẽ tiếp sau X giây'.

    Trả về 0 nếu không có toast (đã hết cooldown). Lấy toast mới nhất (số nhỏ nhất).
    """
    try:
        secs = page.evaluate(
            """() => {
                const toasts = Array.from(document.querySelectorAll('[role="status"]'))
                    .filter(t => t.textContent.includes('vẽ tiếp sau'));
                if (!toasts.length) return 0;
                // Lấy số giây nhỏ nhất (toast mới nhất = countdown thấp nhất).
                let min = Infinity;
                for (const t of toasts) {
                    const m = t.textContent.match(/(\\d+)\\s*giây/);
                    if (m) {
                        const v = parseInt(m[1]);
                        if (v < min) min = v;
                    }
                }
                return min === Infinity ? 0 : min;
            }"""
        )
        return int(secs) if secs else 0
    except Exception:
        return 0


# ===========================================================================
# Tô chính
# ===========================================================================
def paint_dom(
    page,
    cfg: Config,
    plan: pp.PixelPlan,
    ci: CanvasInfo,
    palette: list,  # legacy, không dùng nữa (vẽ màu tùy ý)
    log: Callable[[str], None] = print,
    batch_size: int = 0,
    on_progress: Optional[Callable[[int, int], None]] = None,
) -> int:
    """Tô các ô còn lại. Có rate-limit sliding window + verify + smart skip."""
    reset_color_cache()
    # Patch DevTools detection (module 87105) — đề phòng user mở F12.
    patch_devtools_detection(page, log)
    total = len(plan.cells)
    limit = batch_size if batch_size > 0 else (total - plan.index)
    drawn = 0
    rejected = 0  # số ô bị rate-limit reject

    # Cache màu hiện tại của canvas để:
    #   (1) smart skip: bỏ ô đã đúng màu,
    #   (2) verify_cell: biết màu Ô TRƯỚC KHI VẼ → so before/after (chống quantize
    #       của web — set (255,0,0) nhưng web lưu (212,32,39), so màu set sẽ FAIL nhầm).
    # Cập nhật cache sau mỗi ô vẽ thành công để verify ô tiếp theo đúng.
    current_colors: dict = {}
    # Grid thật của canvas (auto-detect, có thể ≠ GRID_W/GRID_H hardcode cũ).
    gw, gh = ci.grid_w, ci.grid_h
    if cfg.pixel_smart_skip:
        try:
            current_colors = read_canvas_pixels(page, gw, gh)
            before = total - plan.index
            todo = plan.cells[plan.index:]
            keep = pp.filter_changed_cells(todo, current_colors, cfg.pixel_color_tolerance)
            plan.cells = plan.cells[: plan.index] + keep
            log(f"[DOM] Smart skip: {before} ô -> giữ {len(keep)} ô cần đổi "
                f"(grid canvas {gw}×{gh}).")
        except Exception as e:
            log(f"[DOM][Cảnh báo] smart skip lỗi ({e}), tô toàn bộ.")

    # Đảm bảo đang chọn công cụ Bút.
    try:
        pen = page.query_selector(PEN_BTN)
        if pen:
            pen.click()
            log("[DOM] Đã chọn công cụ Bút.")
            time.sleep(0.2)
    except Exception:
        pass

    # Số ô đã vẽ trong 5 phút qua (resume từ progress) — để biết có bị rate-limit dở không.
    now = time.time()
    recent = sum(1 for t in (plan.rate_times or []) if now - t < 300)
    log(f"[DOM] Bắt đầu tô: còn {plan.remaining()} ô, giới hạn {limit}/đợt. "
        f"Web: {cfg.pixel_rate_limit} ô/{cfg.pixel_rate_window}s. "
        f"Đã vẽ {recent} ô trong 5 phút qua (resume). ESC để dừng.")

    last_color: Optional[tuple[int, int, int]] = None

    # === Humanize: vẽ theo NÉT (batch) thay vì từng ô riêng lẻ ===
    # Web datn có server-side detection: nếu POST từng ô riêng + timing đều/tuần tự
    # → flagged → khóa tài khoản [30m,1h,3h,6h,12h,24h,3d,7d].
    # Người thật kéo chuột vẽ 1 vùng (3-12 ô) → web gom 350ms → POST 1 lần với 1
    # activityContext. Tool cũ POST mỗi ô = khác pattern rõ ràng.
    #
    # Chiến lược: gom N ô liên tiếp thành 1 "nét", trong nét nghỉ ngắn (jitter),
    # giữa các nét nghỉ dài (người xem ảnh/chọn màu). Thỉnh thoảng nghỉ siêu dài.
    humanize = bool(getattr(cfg, "pixel_humanize", True))
    stroke_n = 0  # số ô đã vẽ trong nét hiện tại
    stroke_size = random.randint(cfg.pixel_stroke_min, cfg.pixel_stroke_max)
    if not humanize:
        stroke_size = 1  # cũ: vẽ từng ô, không gom nét
    if humanize:
        log(f"[Humanize] BẬT: nét {cfg.pixel_stroke_min}-{cfg.pixel_stroke_max} ô, "
            f"nghỉ giữa ô {cfg.pixel_stroke_cell_min}-{cfg.pixel_stroke_cell_max}s, "
            f"nghỉ giữa nét {cfg.pixel_stroke_gap_min}-{cfg.pixel_stroke_gap_max}s, "
            f"xs nghỉ dài {cfg.pixel_long_break_chance*100:.0f}%.")
    else:
        log("[Humanize] TẮT — vẽ nhanh cũ (cảnh báo: dễ bị flag/khóa).")

    while plan.has_more() and drawn < limit:
        if _should_stop():
            log(f"[DOM] ⏹ Dừng theo ESC. Đã tô {drawn} ô.")
            break

        c = plan.cells[plan.index]
        # Đổi màu khi cần.
        if c.rgb != last_color:
            if not set_color(page, c.rgb, log):
                log(f"[DOM][Lỗi] không set được màu {c.rgb}, bỏ qua ô.")
                plan.index += 1
                continue
            last_color = c.rgb

        # Lấy màu ô TRƯỚC khi vẽ (từ cache) để verify bằng cách so before/after.
        # Web datn làm tròn màu (quantize): set (255,0,0) → lưu (212,32,39). So
        # trước/sau cho kết quả đúng (ô đổi = vẽ OK) thay vì so màu set (lệch).
        before_rgb = current_colors.get((c.x, c.y))

        # Vẽ ô.
        try:
            paint_cell(page, ci, c.x, c.y, humanize=humanize)
        except Exception as e:
            log(f"[DOM][Cảnh báo] vẽ ({c.x},{c.y}) lỗi: {e}")
            plan.index += 1
            continue

        # Verify: so before/after (chống quantize). Dùng grid thật của canvas.
        ok = verify_cell(page, c.x, c.y, c.rgb, grid_w=gw, grid_h=gh, before=before_rgb)
        if ok:
            # Vẽ thành công -> tăng index, ghi timestamp.
            plan.index += 1
            drawn += 1
            stroke_n += 1
            # Cập nhật cache màu: ô nay đã là màu web-làm-tròn của c.rgb.
            # Đọc lại đúng màu sau để cache chính xác (cho verify ô lân cận).
            try:
                after_res = read_cells(page, [(c.x, c.y)], gw, gh)
                if after_res:
                    current_colors[(c.x, c.y)] = after_res[(c.x, c.y)]
            except Exception:
                pass
            plan.rate_times.append(time.time())
            # Log ô đầu tiên + mỗi 10 ô (để theo dõi sát + chẩn đoán).
            if drawn <= 3 or drawn % 10 == 0:
                plan.save()
                log(f"[DOM] ✅ Tô OK ô ({c.x},{c.y}) set={c.rgb} before={before_rgb} "
                    f"-> đã tô {drawn} ô ({plan.index}/{total}).")
                if on_progress:
                    on_progress(plan.index, total)
            # === Humanize timing ===
            if humanize and plan.has_more() and drawn < limit:
                if stroke_n >= stroke_size:
                    # Hết nét → nghỉ dài giữa nét (người xem ảnh/chọn màu tiếp).
                    gap = random.uniform(cfg.pixel_stroke_gap_min,
                                         cfg.pixel_stroke_gap_max)
                    log(f"[Humanize] 🖌️ Nét {stroke_size} ô xong — nghỉ {gap:.1f}s "
                        f"giữa nét (đã tô {drawn}/{limit}).")
                    t0 = time.time()
                    while time.time() - t0 < gap:
                        if _should_stop():
                            break
                        time.sleep(0.5)
                    # Thỉnh thoảng nghỉ siêu dài (người đi làm việc khác).
                    _long_break(cfg, log)
                    # Bắt đầu nét mới với kích thước ngẫu nhiên khác.
                    stroke_n = 0
                    stroke_size = random.randint(cfg.pixel_stroke_min,
                                                 cfg.pixel_stroke_max)
                else:
                    # Còn trong nét → nghỉ ngắn jitter giữa các ô.
                    _human_delay(cfg.pixel_stroke_cell_min,
                                 cfg.pixel_stroke_cell_max)
        else:
            # Bị reject -> KHÔNG tăng index, đọc cooldown từ web rồi chờ.
            # Đọc thêm màu after + toast + đếm ô trong rate-window để chẩn đoán
            # chính xác nguyên nhân (rate-limit thật / ô đúng màu sẵn / tranh chấp).
            rejected += 1
            try:
                after_res = read_cells(page, [(c.x, c.y)], gw, gh)
                after_rgb = after_res.get((c.x, c.y))
            except Exception:
                after_rgb = None
            cooldown = read_cooldown_seconds(page)
            if cooldown <= 0:
                cooldown = 30  # fallback nếu không đọc được toast
            # Trần an toàn: không chờ quá 330s (rate-limit web là 300s) để tránh
            # toast báo sai/không reset khiến worker kẹt.
            cooldown = min(cooldown, 330)
            mm, ss = int(cooldown // 60), int(cooldown % 60)
            # Số ô đã vẽ trong 5 phút qua (cửa sổ rate-limit).
            now = time.time()
            recent = sum(1 for t in (plan.rate_times or []) if now - t < 300)
            # Phân loại nguyên nhân reject dựa trên before/after + rate-window.
            # Khoảng cách before→after: =0 nghĩa là ô hoàn toàn không đổi màu.
            if before_rgb is not None and after_rgb is not None:
                d_after = max(abs(after_rgb[0]-before_rgb[0]),
                              abs(after_rgb[1]-before_rgb[1]),
                              abs(after_rgb[2]-before_rgb[2]))
            else:
                d_after = -1
            # Phân loại: 3 trường hợp.
            # 1) RATE-LIMIT THẬT: đã vẽ gần hết quota (recent >= limit-10) → chờ đúng cooldown.
            # 2) Ô TRANH CHẤP: ô không đổi màu (d_after=0) nhưng recent còn xa limit
            #    → web silent-reject ô đang bị người khác vẽ. Chờ lâu vô ích → skip nhanh.
            # 3) KHÁC: ô đổi ít / không rõ → chờ cooldown rồi thử lại vài lần.
            near_rate_limit = recent >= (cfg.pixel_rate_limit - 10)
            cell_contested = (d_after == 0 and not near_rate_limit)
            if d_after >= 25:
                cat = "verify_anomaly"
                reason = f"Ô ĐÃ đổi màu (Δ={d_after}) nhưng verify FAIL — kiểm tra verify_cell"
            elif near_rate_limit:
                cat = "rate_limit_real"
                reason = f"Rate-limit thật (đã vẽ {recent}/{cfg.pixel_rate_limit} ô trong 5 phút)"
            elif cell_contested:
                cat = "cell_contested"
                reason = (f"Ô không đổi màu, chưa gần rate-limit (đã vẽ {recent} ô) "
                          f"→ ô đang bị tranh chấp, sẽ bỏ qua nhanh")
            else:
                cat = "unknown"
                reason = f"Ô đổi rất ít (Δ={d_after}) — ranh giới quantize/tranh chấp"
            log(f"[DOM] ⏳ Bị reject [{cat}]! Ô ({c.x},{c.y}) set={c.rgb} "
                f"before={before_rgb} after={after_rgb}. {reason}. "
                f"Web chờ {mm}:{ss:02d} (reject {rejected}).")

            # Chiến lược chờ/skip theo phân loại.
            if cat == "cell_contested":
                # Ô tranh chấp: chỉ thử lại 1 lần (chờ ngắn 3s), rồi SKIP luôn.
                # Chờ 30s cho 1 ô bị người khác tranh chấp là phí — bỏ qua, tô ô khác,
                # HELP MODE sẽ quét lại ô này sau.
                if rejected >= 2:
                    log(f"[DOM] ⚠ Ô ({c.x},{c.y}) bị tranh chấp ({rejected} lần) — "
                        f"bỏ qua, tô ô khác (sẽ quét lại sau).")
                    plan.index += 1
                    rejected = 0
                else:
                    # Chờ ngắn 3s rồi thử lại 1 lần.
                    for _ in range(3):
                        if _should_stop():
                            break
                        time.sleep(1)
            elif cat == "rate_limit_real":
                # Rate-limit thật: chờ ĐÚNG cooldown (web báo chính xác).
                wait_target = cooldown + 3
                t0 = time.time()
                while time.time() - t0 < wait_target:
                    if _should_stop():
                        break
                    time.sleep(1)
                if _should_stop():
                    log(f"[DOM] ⏹ Dừng theo ESC trong lúc chờ rate-limit.")
                    break
                log(f"[DOM] ▶ Hết cooldown, vẽ lại ô ({c.x},{c.y}).")
            else:
                # verify_anomaly / unknown: thử lại tối đa 3 lần rồi skip.
                wait_target = min(cooldown + 3, 60)  # không chờ quá 60s cho trường hợp lạ
                t0 = time.time()
                while time.time() - t0 < wait_target:
                    if _should_stop():
                        break
                    time.sleep(1)
                if _should_stop():
                    log(f"[DOM] ⏹ Dừng theo ESC trong lúc chờ.")
                    break
                log(f"[DOM] ▶ Hết chờ, vẽ lại ô ({c.x},{c.y}).")
                if rejected >= 3:
                    log(f"[DOM] ⚠ Ô ({c.x},{c.y}) reject lạ {rejected} lần — bỏ qua, "
                        f"tô ô khác.")
                    plan.index += 1
                    rejected = 0
                rejected = 0
            # Loop sẽ tự vẽ lại ô hiện tại (index không đổi) nếu chưa bỏ qua.

    plan.save()
    if on_progress:
        on_progress(plan.index, total)
    log(f"[DOM] Xong đợt: đã tô {drawn} ô, reject {rejected}. Tổng {plan.index}/{total}.")
    return drawn


# Giữ tương thích với code cũ.
def detect_dom_structure(page, log=print):
    return None
