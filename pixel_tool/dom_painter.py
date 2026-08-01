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

import time
from dataclasses import dataclass
from typing import Callable, Optional

import pixel_painter as pp
from config import Config


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

    def cell_to_page(self, gx: int, gy: int) -> tuple[float, float]:
        """Chuyển ô (gx,gy) sang toạ độ click trên trang (tâm ô)."""
        cx = (gx + 0.5) * self.cell_px_x
        cy = (gy + 0.5) * self.cell_px_y
        sx = cx / self.canvas_w * self.rect_w
        sy = cy / self.canvas_h * self.rect_h
        return (self.rect_x + sx, self.rect_y + sy)


# ===========================================================================
# Đăng nhập + vào trang pixel
# ===========================================================================
def login_and_open_canvas(page, cfg: Config, log: Callable[[str], None] = print) -> bool:
    """Đăng nhập trang chính rồi bấm 'Vẽ Pixel' để vào trang canvas."""
    from screen_painter import is_stopped

    site = (cfg.pixel_site_url or "https://datn.unifolio.io.vn").rstrip("/")
    log(f"[DOM] Mở trang chính: {site}")

    # --- Chủ động mở trang /login để chắc chắn thấy form ---
    login_url = site + "/login"
    try:
        page.goto(login_url, wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        log(f"[DOM][Lỗi] không mở được trang: {e}")
        return False
    page.wait_for_timeout(2000)

    # --- Kiểm tra đã login chưa (URL không còn /login) ---
    already_logged = "/login" not in page.url and not page.query_selector(PASSWORD_SELECTOR)
    if already_logged:
        log("[DOM] Phiên đăng nhập còn hạn → không cần login lại.")
    elif cfg.pixel_username and cfg.pixel_password:
        # --- Đợi ô password xuất hiện (form React có thể load chậm) ---
        try:
            page.wait_for_selector(PASSWORD_SELECTOR, timeout=15000)
        except Exception:
            log("[DOM][Cảnh báo] không thấy ô password sau 15s — thử điền nếu có.")

        log(f"[DOM] Đăng nhập với {cfg.pixel_username}...")
        ok_login = _do_login(page, cfg.pixel_username, cfg.pixel_password, log)
        page.wait_for_timeout(4000)

        # --- Kiểm tra login thành công: URL không còn /login ---
        if "/login" in page.url:
            log("[DOM][Login] Có vẻ sai tài khoản/captcha. Tool dừng cho acc này.")
            log("[DOM][Login] Nếu có captcha → đăng nhập tay rồi chạy lại.")
            return False
        if ok_login:
            log("[DOM][Login] ✅ Đăng nhập thành công.")
    else:
        log("[DOM] Có form đăng nhập nhưng chưa nhập tài khoản trong config.")
        log("[DOM] Tool dừng — hãy nhập username/password hoặc đăng nhập tay.")

    # Nếu chưa ở /pixel → bấm link "Vẽ Pixel".
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
        if is_stopped():
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
        # Click + fill + trigger để React/form nhận giá trị.
        u.click()
        u.fill("")
        u.fill(username)
        p.click()
        p.fill("")
        p.fill(password)
        # Dispatch thêm để chắc chắn React/form bắt sự kiện.
        for el, val in ((u, username), (p, password)):
            try:
                el.evaluate(
                    "(node, v) => {"
                    "  const setter = Object.getOwnPropertyDescriptor("
                    "    window.HTMLInputElement.prototype, 'value').set;"
                    "  setter.call(node, v);"
                    "  node.dispatchEvent(new Event('input', {bubbles: true}));"
                    "  node.dispatchEvent(new Event('change', {bubbles: true}));"
                    "}",
                    val,
                )
            except Exception:
                pass
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
def get_canvas_info(page) -> Optional[CanvasInfo]:
    """Lấy thông tin canvas chính (lớn nhất). None nếu không có."""
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
        return CanvasInfo(
            rect_x=data["rect_x"], rect_y=data["rect_y"],
            rect_w=data["rect_w"], rect_h=data["rect_h"],
            canvas_w=data["canvas_w"], canvas_h=data["canvas_h"],
            cell_px_x=data["canvas_w"] / float(GRID_W),
            cell_px_y=data["canvas_h"] / float(GRID_H),
        )
    except Exception:
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
_last_set_color: Optional[str] = None


def set_color(page, rgb: tuple[int, int, int], log) -> bool:
    """Set màu qua input[type=color]. rgb là tuple (r,g,b) 0-255."""
    global _last_set_color
    hexcode = "#%02X%02X%02X" % rgb
    if _last_set_color == hexcode:
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
            _last_set_color = hexcode
            time.sleep(0.03)  # đợi React cập nhật state (tối thiểu)
            return True
        log(f"[DOM] Set màu {hexcode} thất bại (input không nhận).")
    except Exception as e:
        log(f"[DOM][Cảnh báo] set màu {hexcode} lỗi: {e}")
    return False


def reset_color_cache():
    """Reset cache màu (gọi khi bắt đầu phiên mới)."""
    global _last_set_color
    _last_set_color = None


# Bảng màu legacy — hiện không dùng (vẽ màu tùy ý qua input[type=color]).
def read_palette(page) -> list[tuple[int, int, int]]:
    return list(pp.DEFAULT_PALETTE)


# ===========================================================================
# Vẽ 1 ô + verify + đọc cooldown
# ===========================================================================
def paint_cell(page, ci: CanvasInfo, gx: int, gy: int) -> None:
    """Vẽ 1 ô bằng mouse.move → mouse.down → mouse.up (không delay, vẽ nhanh nhất)."""
    x, y = ci.cell_to_page(gx, gy)
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.up()


def verify_cell(page, gx: int, gy: int, expected: tuple[int, int, int],
                grid_w: int = GRID_W, grid_h: int = GRID_H) -> bool:
    """Đọc lại 1 ô xem có đúng màu expected không (phát hiện rate-limit reject)."""
    res = read_cells(page, [(gx, gy)], grid_w, grid_h)
    if not res:
        return False
    r, g, b = res[(gx, gy)]
    er, eg, eb = expected
    # tolerance 8 (anti-aliasing JPEG)
    return abs(r - er) <= 8 and abs(g - eg) <= 8 and abs(b - eb) <= 8


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
    from screen_painter import is_stopped

    reset_color_cache()
    total = len(plan.cells)
    limit = batch_size if batch_size > 0 else (total - plan.index)
    drawn = 0
    rejected = 0  # số ô bị rate-limit reject

    # Smart skip: đọc toàn bộ canvas, bỏ ô đã đúng màu.
    if cfg.pixel_smart_skip:
        try:
            current = read_canvas_pixels(page, GRID_W, GRID_H)
            before = total - plan.index
            todo = plan.cells[plan.index:]
            keep = pp.filter_changed_cells(todo, current, cfg.pixel_color_tolerance)
            plan.cells = plan.cells[: plan.index] + keep
            log(f"[DOM] Smart skip: {before} ô -> giữ {len(keep)} ô cần đổi.")
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

    log(f"[DOM] Bắt đầu tô: còn {plan.remaining()} ô, giới hạn {limit}/đợt. "
        f"Web: {cfg.pixel_rate_limit} ô/{cfg.pixel_rate_window}s. ESC để dừng.")

    last_color: Optional[tuple[int, int, int]] = None

    while plan.has_more() and drawn < limit:
        if is_stopped():
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

        # Vẽ ô.
        try:
            paint_cell(page, ci, c.x, c.y)
        except Exception as e:
            log(f"[DOM][Cảnh báo] vẽ ({c.x},{c.y}) lỗi: {e}")
            plan.index += 1
            continue

        # Verify ngay sau khi vẽ — phát hiện rate-limit silent reject (không delay).
        ok = verify_cell(page, c.x, c.y, c.rgb)
        if ok:
            # Vẽ thành công -> tăng index, ghi timestamp.
            plan.index += 1
            drawn += 1
            plan.rate_times.append(time.time())
            if drawn % 10 == 0:
                plan.save()
                log(f"[DOM] Đã tô {drawn} ô ({plan.index}/{total}).")
                if on_progress:
                    on_progress(plan.index, total)
            # Không có cooldown giữa các ô - vẽ liên tục cho nhanh nhất.
        else:
            # Bị reject (rate-limit) -> KHÔNG tăng index, đọc cooldown từ web rồi chờ.
            rejected += 1
            cooldown = read_cooldown_seconds(page)
            if cooldown <= 0:
                cooldown = 30  # fallback nếu không đọc được toast
            mm, ss = int(cooldown // 60), int(cooldown % 60)
            log(f"[DOM] ⏳ Bị rate-limit! Ô ({c.x},{c.y}) chưa vẽ được. "
                f"Web báo chờ {mm}:{ss:02d}. NGƯNG TÔ, đợi...")
            # Vẽ lại ô này sau khi chờ (không tăng index).
            wait_target = cooldown + 3  # cộng 3s đệm cho an toàn
            t0 = time.time()
            while time.time() - t0 < wait_target:
                if is_stopped():
                    break
                # Cập nhật countdown mỗi 10s.
                elapsed = time.time() - t0
                remain = wait_target - elapsed
                if int(elapsed) % 10 == 0 and int(elapsed) > 0:
                    # Đọc lại cooldown mới nhất từ web (có thể giảm).
                    new_cd = read_cooldown_seconds(page)
                    if new_cd and new_cd > remain:
                        wait_target = time.time() - t0 + new_cd + 3
                        mm2, ss2 = int(new_cd // 60), int(new_cd % 60)
                        log(f"[DOM] ⏳ Web vẫn báo chờ {mm2}:{ss2:02d}, gia hạn...")
                time.sleep(1)
            if is_stopped():
                log(f"[DOM] ⏹ Dừng theo ESC trong lúc chờ rate-limit.")
                break
            log(f"[DOM] ▶ Hết cooldown, vẽ lại ô ({c.x},{c.y}).")
            # Reset rejected count để không bị loop vô hạn nếu web vẫn khóa.
            if rejected > 20:
                log("[DOM] ⚠ Đã retry nhiều lần vẫn bị khóa — có thể web lỗi. Dừng.")
                break
            # Loop sẽ tự vẽ lại ô hiện tại (index không đổi).

    plan.save()
    if on_progress:
        on_progress(plan.index, total)
    log(f"[DOM] Xong đợt: đã tô {drawn} ô, reject {rejected}. Tổng {plan.index}/{total}.")
    return drawn


# Giữ tương thích với code cũ.
def detect_dom_structure(page, log=print):
    return None
