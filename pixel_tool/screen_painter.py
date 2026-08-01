"""Screen Painter — vẽ tranh pixel lên canvas trên MÀN HÌNH thật.

Khác với pixel_painter.py (mở URL riêng bằng Playwright), module này điều khiển
chuột thật trên trình duyệt ĐÃ ĐĂNG NHẬP sẵn của người dùng — phù hợp với trang
pixel bắt buộc login qua trang chính rồi mới truy cập trang pixel.

Quy trình:
  1. Người dùng canh (calibrate) vị trí canvas: click 2 góc chéo (trên-trái và
     dưới-phải) để tool biết vùng lưới.
  2. Người dùng canh vùng bảng màu: bấm "dò palette", rồi quét một vùng nhỏ quanh
     con trỏ để lấy các ô màu.
  3. Tool chụp canvas, quantize ảnh nguồn theo palette, rồi tự click chuột từng ô
     (chọn màu -> click ô), có cooldown.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import time
from dataclasses import dataclass
from typing import Callable, Optional

import mss
from PIL import Image

import pixel_painter as pp
from config import Config


# ===========================================================================
# Cờ dừng khẩn (đọc bởi vòng vẽ). ESC hotkey đặt nó = True.
# ===========================================================================
STOP_FLAG = {"stop": False}


def request_stop() -> None:
    STOP_FLAG["stop"] = True


def clear_stop() -> None:
    STOP_FLAG["stop"] = False


def is_stopped() -> bool:
    return STOP_FLAG["stop"]


# ===========================================================================
# Chuột thật (ctypes) — Windows
# ===========================================================================
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
INPUT_MOUSE = 0

user32 = ctypes.windll.user32
# Lấy DPI scale để SetCursorPos dùng toạ độ vật lý đúng.
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def screen_size() -> tuple[int, int]:
    """Kích thước màn hình vật lý (pixel)."""
    return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


def move_to(x: int, y: int) -> None:
    user32.SetCursorPos(int(x), int(y))


def click_at(x: int, y: int, delay_ms: int = 60) -> None:
    """Di chuyển tới (x,y) rồi nhấn-nhả chuột trái."""
    move_to(x, y)
    time.sleep(delay_ms / 1000.0)
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.02)
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


def get_cursor_pos() -> tuple[int, int]:
    """Lấy toạ độ chuột hiện tại."""
    pt = ctypes.wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


# ===========================================================================
# Chụp màn hình
# ===========================================================================
def grab_screen(bbox: Optional[dict] = None) -> Image.Image:
    """Chụp toàn màn hình hoặc vùng bbox {x,y,width,height} (toạ độ vật lý)."""
    with mss.mss() as sct:
        mon = sct.monitors[1]
        if bbox:
            mon = {
                "left": int(bbox["x"]), "top": int(bbox["y"]),
                "width": int(bbox["width"]), "height": int(bbox["height"]),
            }
        raw = sct.grab(mon)
    return Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")


def grab_screen_colors(
    canvas: "CanvasRegion", grid_w: int, grid_h: int
) -> dict[tuple[int, int], tuple[int, int, int]]:
    """Chụp canvas, lấy màu trung tâm mỗi ô. Trả về map (x,y) -> rgb."""
    img = grab_screen(canvas.as_dict()).convert("RGB")
    w, h = img.size
    cw = w / grid_w
    ch = h / grid_h
    px = img.load()
    out: dict[tuple[int, int], tuple[int, int, int]] = {}
    for y in range(grid_h):
        for x in range(grid_w):
            cx = int((x + 0.5) * cw)
            cy = int((y + 0.5) * ch)
            cx = min(max(cx, 0), w - 1)
            cy = min(max(cy, 0), h - 1)
            out[(x, y)] = px[cx, cy]
    return out


# ===========================================================================
# CanvasRegion: vùng canvas trên màn hình
# ===========================================================================
@dataclass
class CanvasRegion:
    x: int   # góc trên-trái (toạ độ màn hình vật lý)
    y: int
    width: int
    height: int

    @classmethod
    def from_corners(cls, x1: int, y1: int, x2: int, y2: int) -> "CanvasRegion":
        x = min(x1, x2)
        y = min(y1, y2)
        w = abs(x2 - x1)
        h = abs(y2 - y1)
        return cls(x=x, y=y, width=w, height=h)

    def cell_center(self, gx: int, gy: int, grid_w: int, grid_h: int) -> tuple[int, int]:
        """Tâm ô (gx,gy) trong lưới grid_w x grid_h, theo toạ độ màn hình."""
        cw = self.width / grid_w
        ch = self.height / grid_h
        return int(self.x + (gx + 0.5) * cw), int(self.y + (gy + 0.5) * ch)

    def as_dict(self) -> dict:
        return {"x": self.x, "y": self.y, "width": self.width, "height": self.height}


# ===========================================================================
# Dò palette từ màn hình (người dùng chỉ vùng)
# ===========================================================================
@dataclass
class PaletteRegion:
    x: int
    y: int
    width: int
    height: int

    def as_dict(self) -> dict:
        return {"x": self.x, "y": self.y, "width": self.width, "height": self.height}


def detect_palette_from_screen(
    region: PaletteRegion, max_colors: int = 64
) -> list[tuple[int, int, int]]:
    """Quét vùng palette trên màn hình, gom các màu đặc trưng.

    Phương pháp: lấy mẫu lưới thưa trong vùng, quantize về bước 48 (giảm sắc),
    đếm tần suất, trả về các màu xuất hiện nhiều (bỏ near-trắng/near-đen trừ khi
    đó là majority).
    """
    img = grab_screen(region.as_dict()).convert("RGB")
    img = img.resize((min(img.width, 160), min(img.height, 160)), Image.LANCZOS)
    px = img.load()
    counts: dict[tuple[int, int, int], int] = {}
    for y in range(img.height):
        for x in range(img.width):
            r, g, b = px[x, y]
            # lượng tử hoá về bước 48 để gom màu gần nhau
            key = ((r // 48) * 48, (g // 48) * 48, (b // 48) * 48)
            counts[key] = counts.get(key, 0) + 1
    if not counts:
        return list(pp.DEFAULT_PALETTE)
    # Sắp xếp theo tần suất, lấy top max_colors
    ranked = sorted(counts.items(), key=lambda kv: -kv[1])
    colors = [c for c, _ in ranked[:max_colors]]
    return colors


# ===========================================================================
# Vẽ thật trên màn hình
# ===========================================================================
def find_swatch_point_for_color(
    region: PaletteRegion,
    target: tuple[int, int, int],
    page_palette: list[tuple[int, int, int]],
) -> Optional[tuple[int, int]]:
    """Tìm toạ độ điểm trong vùng palette có màu gần `target` nhất.

    Quét toàn bộ pixel, lấy tâm cụm điểm khớp màu (tránh click vào viền nút).
    Trả về toạ độ màn hình.
    """
    img = grab_screen(region.as_dict()).convert("RGB")
    w, h = img.size
    px = img.load()
    xs: list[int] = []
    ys: list[int] = []
    # tolerance hào phóng để bắt được nút dù hiển thị hơi khác
    tol = 80
    for y in range(0, h, 2):  # bước 2 cho nhanh, vẫn đủ đặc trưng
        for x in range(0, w, 2):
            if pp._color_dist(px[x, y], target) <= tol:
                xs.append(x)
                ys.append(y)
    if not xs:
        # fallback: điểm gần nhất toàn cục
        best = None
        best_d = 1 << 30
        for y in range(0, h, 3):
            for x in range(0, w, 3):
                d = pp._color_dist(px[x, y], target)
                if d < best_d:
                    best_d = d
                    best = (x, y)
        if best is None or best_d > 120:
            return None
        return (region.x + best[0], region.y + best[1])
    # tâm cụm -> click giữa nút màu, đỡ trượt ra viền
    cx = sum(xs) // len(xs)
    cy = sum(ys) // len(ys)
    return (region.x + cx, region.y + cy)


def paint_on_screen(
    cfg: Config,
    plan: pp.PixelPlan,
    canvas: CanvasRegion,
    palette_region: Optional[PaletteRegion],
    page_palette: list[tuple[int, int, int]],
    log: Callable[[str], None] = print,
    batch_size: int = 0,
    on_progress: Optional[Callable[[int, int], None]] = None,
) -> int:
    """Vẽ các ô còn lại trong plan lên màn hình thật. Trả về số ô đã vẽ."""
    total = len(plan.cells)
    gw, gh = plan.grid_w, plan.grid_h

    # Smart skip: chụp canvas rồi chỉ vẽ ô sai màu.
    if cfg.pixel_smart_skip:
        try:
            current = grab_screen_colors(canvas, gw, gh)
            before = total - plan.index
            todo = plan.cells[plan.index:]
            keep = pp.filter_changed_cells(todo, current, cfg.pixel_color_tolerance)
            plan.cells = plan.cells[: plan.index] + keep
            log(f"[Pixel] Smart skip: {before} ô còn lại -> giữ {len(keep)} ô cần đổi màu.")
        except Exception as e:
            log(f"[Pixel][Cảnh báo] Smart skip thất bại ({e}), vẽ toàn bộ.")

    limit = batch_size if batch_size > 0 else (len(plan.cells) - plan.index)
    drawn = 0
    log(f"[Pixel] Bắt đầu vẽ: còn {plan.remaining()} ô, sẽ vẽ {min(limit, plan.remaining())}.")
    log(f"[Pixel] ⚠️ Nhấn ESC bất cứ lúc nào để DỪNG NGAY.")
    last_color: Optional[tuple[int, int, int]] = None
    while plan.has_more() and drawn < limit:
        if is_stopped():
            log(f"[Pixel] ⏹ Đã dừng theo ESC. Đã vẽ {drawn} ô đợt này.")
            break
        c = plan.cells[plan.index]
        # 1) chọn màu (chỉ đổi khi sang màu mới)
        if c.rgb != last_color and palette_region is not None:
            try:
                pt = find_swatch_point_for_color(
                    palette_region, c.rgb, page_palette
                )
                if pt:
                    click_at(pt[0], pt[1], delay_ms=80)
                    time.sleep(0.05)
                    last_color = c.rgb
                else:
                    log(f"[Pixel][Cảnh báo] không tìm thấy nút màu gần {c.rgb}.")
            except Exception as e:
                log(f"[Pixel][Cảnh báo] không chọn được màu {c.rgb}: {e}")
        # 2) click ô
        ox, oy = canvas.cell_center(c.x, c.y, gw, gh)
        try:
            click_at(ox, oy, delay_ms=50)
        except Exception as e:
            log(f"[Pixel][Cảnh báo] lỗi click ô ({c.x},{c.y}): {e}")
        plan.index += 1
        drawn += 1
        last_color = c.rgb
        if drawn % 5 == 0:
            plan.save()
            log(f"[Pixel] Đã vẽ {drawn} ô (vị trí {plan.index}/{total}).")
            if on_progress:
                on_progress(plan.index, total)
        if plan.has_more() and drawn < limit and not is_stopped():
            pp.sleep_jitter(cfg.pixel_cooldown_seconds, cfg.pixel_jitter_seconds)
    plan.save()
    if on_progress:
        on_progress(plan.index, total)
    log(f"[Pixel] Xong đợt: đã vẽ {drawn} ô. Tổng tiến độ {plan.index}/{total}.")
    return drawn
