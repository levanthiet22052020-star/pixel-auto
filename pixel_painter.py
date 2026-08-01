"""Pixel Painter — biến ảnh thường thành tranh pixel rồi tự vẽ lên canvas web.

Pipeline:
  1. Đọc ảnh → resize về lưới grid_w x grid_h (LANCZOS).
  2. Quantize từng ô về màu gần nhất trong palette (dithering tùy chọn).
  3. (Tùy chọn) bỏ ô nền, bỏ ô đã đúng màu (smart skip).
  4. Playwright click lần lượt: chọn màu trong palette UI -> click ô (x, y).

Dùng cùng session Chrome với phần check-in FB (BrowserManager).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import time
from dataclasses import dataclass, asdict
from typing import Callable, Optional

from PIL import Image

from config import Config


# ===========================================================================
# Palette mặc định — 63 màu chính thức của wplace.io
# (Nguồn: BlueMarble src/utils.js:421-486, bỏ id 0 "Transparent" vì RGB trùng Black)
# Dùng làm fallback cuối cùng khi không dò được palette từ UI và không có file.
# ===========================================================================
_WPLACE_PALETTE: list[tuple[int, int, int]] = [
    # id 1-31: free colors
    (0, 0, 0), (60, 60, 60), (120, 120, 120), (210, 210, 210), (255, 255, 255),
    (96, 0, 24), (237, 28, 36), (255, 127, 39), (246, 170, 9), (249, 221, 59),
    (255, 250, 188), (14, 185, 104), (19, 230, 123), (135, 255, 94), (12, 129, 110),
    (16, 174, 166), (19, 225, 190), (40, 80, 158), (64, 147, 228), (96, 247, 242),
    (107, 80, 246), (153, 177, 251), (120, 12, 153), (170, 56, 185), (224, 159, 249),
    (203, 0, 122), (236, 31, 128), (243, 141, 169), (104, 70, 52), (149, 104, 42),
    (248, 178, 119),
    # id 32-63: premium colors
    (170, 170, 170), (165, 14, 30), (250, 128, 114), (228, 92, 26), (214, 181, 148),
    (156, 132, 49), (197, 173, 49), (232, 212, 95), (74, 107, 58), (90, 148, 74),
    (132, 197, 115), (15, 121, 159), (187, 250, 242), (125, 199, 255), (77, 49, 184),
    (74, 66, 132), (122, 113, 196), (181, 174, 241), (219, 164, 99), (209, 128, 81),
    (255, 197, 165), (155, 82, 73), (209, 128, 120), (250, 182, 164), (123, 99, 82),
    (156, 132, 107), (51, 57, 65), (109, 117, 141), (179, 185, 209), (109, 100, 63),
    (148, 140, 107), (205, 197, 158),
]


def _web_safe_palette() -> list[tuple[int, int, int]]:
    """Web-safe 216 màu — chỉ dùng khi cần thử nghiệm so sánh."""
    steps = (0, 51, 102, 153, 204, 255)
    return [(r, g, b) for r in steps for g in steps for b in steps]


DEFAULT_PALETTE: list[tuple[int, int, int]] = list(_WPLACE_PALETTE)


# ===========================================================================
# Đọc palette từ file text — mỗi dòng 1 mã #RRGGBB (bỏ qua dòng trống/comment)
# ===========================================================================
_HEX_RE = re.compile(r"#?([0-9a-fA-F]{6})")


def load_palette_from_text(path: str) -> list[tuple[int, int, int]]:
    colors: list[tuple[int, int, int]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") and len(line.lstrip("#")) != 6:
                # dòng comment (# chữ... ) nhưng không phải hex 6 ký tự -> bỏ qua
                m = _HEX_RE.search(line)
                if not m:
                    continue
            m = _HEX_RE.search(line)
            if not m:
                continue
            h = m.group(1)
            colors.append((int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)))
    return colors or list(DEFAULT_PALETTE)


# ===========================================================================
# Cấu trúc dữ liệu
# ===========================================================================
@dataclass
class Cell:
    x: int               # cột (0..grid_w-1)
    y: int               # dòng (0..grid_h-1)
    rgb: tuple[int, int, int]


# ===========================================================================
# Xử lý màu
# ===========================================================================
def nearest_color(rgb: tuple[int, int, int], palette: list[tuple[int, int, int]]) -> tuple[int, int, int]:
    """Tìm màu gần nhất trong palette theo khoảng cách Euclidean RGB."""
    r, g, b = rgb
    best = palette[0]
    best_d = 1 << 30
    for (pr, pg, pb) in palette:
        d = (r - pr) ** 2 + (g - pg) ** 2 + (b - pb) ** 2
        if d < best_d:
            best_d = d
            best = (pr, pg, pb)
    return best


def _color_dist(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2) ** 0.5


def _is_bg(rgb: tuple[int, int, int], threshold: int = 30) -> bool:
    """Co ô là nền nếu gần trắng hoặc gần đen."""
    r, g, b = rgb
    if abs(255 - r) + abs(255 - g) + abs(255 - b) <= threshold:
        return True
    if r + g + b <= threshold:
        return True
    return False


# ===========================================================================
# Ảnh -> danh sách ô pixel
# ===========================================================================
def image_to_pixels(
    img_path: str,
    grid_w: int,
    grid_h: int,
    palette: list[tuple[int, int, int]],
    dither: bool = False,
    bg_skip: bool = False,
    bg_threshold: int = 30,
    offset_x: int = 0,
    offset_y: int = 0,
) -> list[Cell]:
    """Đọc ảnh, resize về grid_w x grid_h, quantize theo palette.

    Trả về danh sách Cell cần vẽ (theo thứ tự quét trên-dưới, trái-phải).
    offset_x/y: cộng thêm vào tọa độ ô để đặt ảnh ở vị trí khác (0,0) trên canvas.
    """
    img = Image.open(img_path).convert("RGB")
    img = img.resize((grid_w, grid_h), Image.LANCZOS)

    if dither and palette:
        # Floyd-Steinberg dither giới hạn bởi palette.
        pal_img = Image.new("P", (1, 1))
        flat: list[int] = []
        for c in palette[:256]:
            flat.extend(c)
        pal_img.putpalette(flat)
        quant = img.quantize(colors=min(len(palette), 256), palette=pal_img).convert("RGB")
        src = quant
    else:
        src = img

    px = src.load()
    cells: list[Cell] = []
    for y in range(grid_h):
        for x in range(grid_w):
            rgb = px[x, y]
            if isinstance(rgb, int):
                rgb = (rgb, rgb, rgb)
            q = nearest_color(rgb, palette) if palette else rgb
            if bg_skip and _is_bg(q, bg_threshold):
                continue
            cells.append(Cell(x=x + offset_x, y=y + offset_y, rgb=q))
    return cells


def render_preview(
    cells: list[Cell],
    grid_w: int,
    grid_h: int,
    cell_px: int = 10,
    bg: tuple[int, int, int] = (240, 240, 240),
) -> Image.Image:
    """Vẽ ảnh preview từ danh sách Cell để người dùng xem trước kết quả."""
    img = Image.new("RGB", (grid_w * cell_px, grid_h * cell_px), bg)
    px = img.load()
    for c in cells:
        r, g, b = c.rgb
        for dy in range(cell_px):
            for dx in range(cell_px):
                px[c.x * cell_px + dx, c.y * cell_px + dy] = (r, g, b)
    return img


# ===========================================================================
# Smart skip: chụp canvas rồi chỉ giữ ô chưa đúng màu
# ===========================================================================
def capture_canvas_colors(
    page,
    bbox: dict,
    grid_w: int,
    grid_h: int,
) -> dict[tuple[int, int], tuple[int, int, int]]:
    """Chụp canvas, lấy màu trung tâm mỗi ô. Trả về map (x,y) -> rgb."""
    import io
    png_bytes = page.screenshot(clip=bbox)
    img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    w, h = img.size
    cell_w = w / grid_w
    cell_h = h / grid_h
    px = img.load()
    out: dict[tuple[int, int], tuple[int, int, int]] = {}
    for y in range(grid_h):
        for x in range(grid_w):
            cx = int((x + 0.5) * cell_w)
            cy = int((y + 0.5) * cell_h)
            cx = min(max(cx, 0), w - 1)
            cy = min(max(cy, 0), h - 1)
            out[(x, y)] = px[cx, cy]
    return out


def filter_changed_cells(
    cells: list[Cell],
    current: dict[tuple[int, int], tuple[int, int, int]],
    tolerance: int = 24,
) -> list[Cell]:
    """Chỉ giữ Cell có màu khác màu hiện tại quá `tolerance`."""
    keep: list[Cell] = []
    for c in cells:
        cur = current.get((c.x, c.y))
        if cur is None or _color_dist(cur, c.rgb) > tolerance:
            keep.append(c)
    return keep


def filter_cells_by_x(
    cells: list[Cell],
    x_start: int,
    x_end: int,
) -> list[Cell]:
    """Chỉ giữ Cell có x_start <= x <= x_end (dùng cho multi-account chia cột)."""
    if x_start is None or x_end is None:
        return list(cells)
    return [c for c in cells if x_start <= c.x <= x_end]


def slice_plan_by_x(
    plan: "PixelPlan",
    x_start: int,
    x_end: int,
    progress_path: str = "",
) -> "PixelPlan":
    """Tạo PixelPlan con chỉ chứa các ô trong dải cột [x_start, x_end].

    Dùng cho multi-account: mỗi tài khoản vẽ 1 dải cột của cùng bức tranh.
    progress_path phải khác nhau giữa các acc để resume không lẫn.
    """
    sub_cells = filter_cells_by_x(plan.cells, x_start, x_end)
    return PixelPlan(
        cells=sub_cells,
        index=0,
        grid_w=plan.grid_w,
        grid_h=plan.grid_h,
        progress_path=progress_path,
        rate_times=[],
    )


def split_columns_for_accounts(
    plan: "PixelPlan",
    n_accounts: int,
    base_progress_path: str = "",
    x_min: Optional[int] = None,
    x_max: Optional[int] = None,
) -> list[tuple[int, int, str]]:
    """Chia dải cột [x_min..x_max] thành n_accounts dải liền nhau KHÔNG chồng nhau.

    Trả về list [(x_start, x_end, progress_path), ...] theo thứ tự acc 0..n-1.
    Mỗi dải = một dải cột liên tục; tổng phủ kín dải [x_min..x_max], không đè.
    progress_path khác nhau để resume độc lập giữa các acc.

    Mặc định x_min/x_max = 0..grid_w-1. Với multi-account, NÊN truyền x_min/x_max
    = phạm vi ô THẬT của ảnh (lấy từ min/max cell.x) để chia đúng —— nếu không,
    ảnh hẹp hơn grid sẽ khiến các acc phụ nhận dải rỗng và bị bỏ qua.
    """
    if n_accounts < 1:
        n_accounts = 1
    gw = plan.grid_w
    if x_min is None:
        x_min = 0
    if x_max is None:
        x_max = gw - 1
    # Lưu ý: KHÔNG kẹp x_min/x_max về [0..grid_w-1] vì có thể người dùng đặt
    # pixel_offset_x > 0 (ảnh không bắt đầu ở cột 0) → ô thật có x vượt grid_w.
    # Dùng trực tiếp phạm vi ô thật từ min/max cell.x do multi_account truyền vào.
    if x_max < x_min:
        x_min, x_max = x_max, x_min
    total_cols = x_max - x_min + 1
    bounds: list[tuple[int, int, str]] = []
    # Chia đều theo số cột: mỗi acc nhận floor/ceil sao cho tổng = total_cols.
    base = total_cols // n_accounts
    rem = total_cols % n_accounts
    cur = x_min
    base_dir = os.path.dirname(base_progress_path) if base_progress_path else os.path.dirname(
        os.path.abspath(_default_progress_path()))
    base_name = os.path.splitext(os.path.basename(base_progress_path))[0] if base_progress_path else "pixel_progress"
    for i in range(n_accounts):
        cols = base + (1 if i < rem else 0)  # các acc đầu nhận thêm 1 cột nếu dư
        if cols <= 0:
            bounds.append((cur, cur - 1, ""))  # dải rỗng (không ô nào)
            continue
        x0 = cur
        x1 = cur + cols - 1
        cur = x1 + 1
        pp_path = os.path.join(base_dir, f"{base_name}_acc{i+1}.json")
        bounds.append((x0, x1, pp_path))
    return bounds


# ===========================================================================
# PixelPlan: theo dõi tiến độ, hỗ trợ resume
# ===========================================================================
def _image_signature(cfg: Config) -> str:
    """Chữ ký nhận diện ảnh+grid: đường dẫn + size + mtime + kích thước grid.

    Dùng để invalidate file progress khi user đổi ảnh hoặc đổi grid — tránh
    resume nhầm cells của ảnh cũ.
    """
    path = cfg.pixel_image_path or ""
    try:
        st = os.stat(path)
        mtime_size = f"{int(st.st_mtime)}:{st.st_size}"
    except OSError:
        mtime_size = "0:0"
    sig = f"{path}|{mtime_size}|{cfg.pixel_grid_w}x{cfg.pixel_grid_h}"
    return hashlib.md5(sig.encode("utf-8")).hexdigest()


@dataclass
class PixelPlan:
    cells: list[Cell]
    index: int = 0
    grid_w: int = 100
    grid_h: int = 100
    progress_path: str = ""
    # Timestamp các ô đã vẽ thành công (epoch) để giữ rate-limit khi tắt/mở lại.
    rate_times: list = None
    # Chữ ký ảnh+grid — để load() nhận diện progress cũ của ảnh khác và bỏ qua.
    image_sig: str = ""

    def __post_init__(self):
        if self.rate_times is None:
            self.rate_times = []

    @classmethod
    def from_image(cls, cfg: Config, palette: list[tuple[int, int, int]]) -> "PixelPlan":
        cells = image_to_pixels(
            cfg.pixel_image_path,
            cfg.pixel_grid_w,
            cfg.pixel_grid_h,
            palette,
            dither=cfg.pixel_dither,
            bg_skip=cfg.pixel_bg_skip,
            offset_x=getattr(cfg, "pixel_offset_x", 0),
            offset_y=getattr(cfg, "pixel_offset_y", 0),
        )
        return cls(
            cells=cells,
            grid_w=cfg.pixel_grid_w,
            grid_h=cfg.pixel_grid_h,
            progress_path=cfg.pixel_progress_path or _default_progress_path(),
            image_sig=_image_signature(cfg),
        )

    @classmethod
    def load(cls, path: str, cfg: Optional[Config] = None) -> Optional["PixelPlan"]:
        if not path or not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Invalidate progress nếu chữ ký ảnh+grid khác hiện tại (user đổi ảnh/grid).
        if cfg is not None:
            cur_sig = _image_signature(cfg)
            saved_sig = data.get("image_sig", "")
            if saved_sig and saved_sig != cur_sig:
                return None  # file cũ của ảnh khác → bỏ qua, tạo plan mới.
        cells = [Cell(x=c[0], y=c[1], rgb=tuple(c[2])) for c in data.get("cells", [])]
        # Rate-limit: chỉ giữ timestamp trong 5 phút gần nhất (cửa sổ trượt).
        now = time.time()
        rate_times = [float(t) for t in data.get("rate_times", [])
                      if now - float(t) < 300]
        return cls(
            cells=cells,
            index=data.get("index", 0),
            grid_w=data.get("grid_w", 100),
            grid_h=data.get("grid_h", 100),
            progress_path=path,
            rate_times=rate_times,
            image_sig=data.get("image_sig", ""),
        )

    def save(self) -> None:
        if not self.progress_path:
            return
        # Chỉ lưu timestamp trong 10 phút gần nhất (đỡ file lớn, đủ cho rate-limit).
        now = time.time()
        rt = [t for t in (self.rate_times or []) if now - t < 600]
        data = {
            "grid_w": self.grid_w,
            "grid_h": self.grid_h,
            "index": self.index,
            "cells": [[c.x, c.y, list(c.rgb)] for c in self.cells],
            "rate_times": rt,
            "saved_at": now,
            "image_sig": self.image_sig,
        }
        tmp = self.progress_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, self.progress_path)

    def has_more(self) -> bool:
        return self.index < len(self.cells)

    def remaining(self) -> int:
        return len(self.cells) - self.index


def _default_progress_path() -> str:
    try:
        from config import app_dir
    except Exception:
        app_dir = lambda: os.path.dirname(os.path.abspath(__file__))  # type: ignore
    return os.path.join(app_dir(), "pixel_progress.json")


# ===========================================================================
# Playwright: dò canvas, palette, và vẽ
# ===========================================================================
# CSS selector dự phòng cho phần tử canvas/lưới.
CANVAS_SELECTORS = [
    "canvas",
    "[data-canvas]",
    "[class*='pixel-canvas' i]",
    "[class*='pixelgrid' i]",
    "[class*='grid-canvas' i]",
    "div[role='img'][class*='canvas' i]",
    "[class*='canvas' i]",
    "[class*='pixel' i][class*='grid' i]",
    "[class*='grid' i][class*='container' i]",
]

# CSS selector cho các nút màu trong bảng chọn màu của trang.
PALETTE_SWATCH_SELECTORS = [
    "[data-color]",
    "[role='option'][aria-label]",
    "button[class*='color' i]",
    "[class*='palette' i] [class*='color' i]",
    "[class*='swatch' i]",
]


@dataclass
class CanvasGeometry:
    x: float    # góc trên trái (page coords)
    y: float
    width: float
    height: float


def detect_canvas(page, cfg: Config, log: Callable[[str], None]) -> Optional[CanvasGeometry]:
    """Dò bounding box của canvas. Nếu config có ghi đè tọa độ thì dùng."""
    if cfg.pixel_canvas_origin_x and cfg.pixel_cell_w:
        gw, gh = cfg.pixel_grid_w, cfg.pixel_grid_h
        geo = CanvasGeometry(
            x=cfg.pixel_canvas_origin_x,
            y=cfg.pixel_canvas_origin_y,
            width=cfg.pixel_cell_w * gw,
            height=cfg.pixel_cell_h * gh,
        )
        log(f"[Pixel] Dùng tọa độ canvas từ config: {geo}")
        return geo
    for sel in CANVAS_SELECTORS:
        try:
            el = page.query_selector(sel)
            if el:
                bb = el.bounding_box()
                if bb and bb["width"] > 10 and bb["height"] > 10:
                    geo = CanvasGeometry(
                        x=bb["x"], y=bb["y"], width=bb["width"], height=bb["height"]
                    )
                    log(f"[Pixel] Dò thấy canvas '{sel}': {geo}")
                    return geo
        except Exception as e:
            log(f"[Pixel][Cảnh báo] selector '{sel}' lỗi: {e}")
    log("[Pixel][Lỗi] Không dò thấy canvas. Hãy mở trang rồi chỉnh CANVAS_SELECTORS "
        "hoặc nhập tọa độ thủ công trong config.")
    return None


def detect_palette(
    page,
    cfg: Config,
    log: Callable[[str], None],
) -> list[tuple[int, int, int]]:
    """Dò palette thực tế từ UI. Fallback: file -> web-safe."""
    found: list[tuple[int, int, int]] = []
    for sel in PALETTE_SWATCH_SELECTORS:
        try:
            els = page.query_selector_all(sel)
            for el in els[:64]:
                color = _extract_color(el)
                if color and color not in found:
                    found.append(color)
            if found:
                break
        except Exception:
            continue
    if found:
        log(f"[Pixel] Dò thấy {len(found)} màu trên trang.")
        return found
    if cfg.pixel_palette_path and os.path.exists(cfg.pixel_palette_path):
        pal = load_palette_from_text(cfg.pixel_palette_path)
        log(f"[Pixel] Dùng palette từ file: {len(pal)} màu.")
        return pal
    log(f"[Pixel] Dùng palette mặc định (wplace {len(DEFAULT_PALETTE)} màu).")
    return list(DEFAULT_PALETTE)


def _extract_color(el) -> Optional[tuple[int, int, int]]:
    """Lấy màu RGB từ 1 element swatch (style/aria-label/data-color)."""
    # 1) data-color
    try:
        dc = el.get_attribute("data-color")
        if dc:
            c = _parse_css_color(dc)
            if c:
                return c
    except Exception:
        pass
    # 2) aria-label chứa màu hex/tên
    try:
        label = el.get_attribute("aria-label") or ""
        c = _parse_css_color(label)
        if c:
            return c
    except Exception:
        pass
    # 3) background-color computed style
    try:
        bg = el.evaluate("e => getComputedStyle(e).backgroundColor")
        c = _parse_css_color(bg)
        if c:
            return c
    except Exception:
        pass
    return None


def _parse_css_color(s: str) -> Optional[tuple[int, int, int]]:
    """Phân tích #RRGGBB, rgb(r,g,b), hoặc tên màu cơ bản."""
    if not s:
        return None
    s = s.strip()
    m = _HEX_RE.search(s)
    if m:
        h = m.group(1)
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    m = re.search(r"rgba?\(\s*(\d+)[,\s]+(\d+)[,\s]+(\d+)", s)
    if m:
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    named = {
        "black": (0, 0, 0), "white": (255, 255, 255), "red": (255, 0, 0),
        "lime": (0, 255, 0), "blue": (0, 0, 255), "yellow": (255, 255, 0),
        "cyan": (0, 255, 255), "magenta": (255, 0, 255), "gray": (128, 128, 128),
        "grey": (128, 128, 128), "orange": (255, 165, 0), "pink": (255, 192, 203),
        "purple": (128, 0, 128), "green": (0, 128, 0), "brown": (165, 42, 42),
    }
    key = s.lower()
    return named.get(key)


def click_palette_color(
    page,
    rgb: tuple[int, int, int],
    page_palette: list[tuple[int, int, int]],
    log: Callable[[str], None],
) -> bool:
    """Click nút màu gần nhất trong palette UI."""
    target = nearest_color(rgb, page_palette)
    # Tìm element có màu khớp.
    for sel in PALETTE_SWATCH_SELECTORS:
        try:
            els = page.query_selector_all(sel)
            for el in els:
                c = _extract_color(el)
                if c == target:
                    el.click()
                    return True
        except Exception:
            continue
    log(f"[Pixel][Cảnh báo] Không tìm thấy nút màu {target} để click.")
    return False


def paint(
    page,
    cfg: Config,
    plan: PixelPlan,
    page_palette: list[tuple[int, int, int]],
    geo: CanvasGeometry,
    log: Callable[[str], None] = print,
    batch_size: int = 0,
    dry_run: bool = False,
) -> int:
    """Vẽ các ô còn lại trong plan. Trả về số ô đã vẽ (thực sự click)."""
    if not cfg.pixel_url:
        log("[Pixel][Lỗi] Chưa đặt pixel_url.")
        return 0
    page.goto(cfg.pixel_url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(1200)

    cell_w = geo.width / plan.grid_w
    cell_h = geo.height / plan.grid_h

    # Smart skip: chụp canvas rồi lọc ô chưa đúng màu.
    if cfg.pixel_smart_skip and not dry_run:
        try:
            current = capture_canvas_colors(
                page,
                {"x": geo.x, "y": geo.y, "width": geo.width, "height": geo.height},
                plan.grid_w,
                plan.grid_h,
            )
            before = len(plan.cells)
            # Lọc từ index hiện tại trở đi (không đụng ô đã vẽ).
            todo = plan.cells[plan.index:]
            keep = filter_changed_cells(todo, current, cfg.pixel_color_tolerance)
            plan.cells = plan.cells[: plan.index] + keep
            log(f"[Pixel] Smart skip: {before - plan.index} ô còn lại -> giữ {len(keep)} ô cần đổi màu.")
        except Exception as e:
            log(f"[Pixel][Cảnh báo] Smart skip thất bại ({e}), vẽ toàn bộ.")

    total = len(plan.cells)
    limit = batch_size if batch_size > 0 else (total - plan.index)
    drawn = 0
    log(f"[Pixel] Bắt đầu vẽ: còn {plan.remaining()} ô, sẽ vẽ {min(limit, plan.remaining())} ô.")
    while plan.has_more() and drawn < limit:
        c = plan.cells[plan.index]
        if dry_run:
            log(f"[Pixel][dry] ô ({c.x},{c.y}) rgb{c.rgb}")
        else:
            try:
                click_palette_color(page, c.rgb, page_palette, log)
                px_x = geo.x + (c.x + 0.5) * cell_w
                px_y = geo.y + (c.y + 0.5) * cell_h
                page.mouse.click(px_x, px_y)
            except Exception as e:
                log(f"[Pixel][Cảnh báo] lỗi ô ({c.x},{c.y}): {e}")
        plan.index += 1
        drawn += 1
        if drawn % 25 == 0:
            log(f"[Pixel] Đã vẽ {drawn} / {min(limit, total)} (vị trí {plan.index}/{total})")
            plan.save()
        if plan.has_more() and drawn < limit:
            sleep_jitter(cfg.pixel_cooldown_seconds, cfg.pixel_jitter_seconds)
    plan.save()
    log(f"[Pixel] Xong đợt này: đã vẽ {drawn} ô. Tổng tiến độ {plan.index}/{total}.")
    return drawn


def sleep_jitter(cooldown: float, jitter: float) -> None:
    t = cooldown + random.uniform(-jitter, jitter)
    if t > 0:
        time.sleep(t)


def build_palette(cfg: Config) -> list[tuple[int, int, int]]:
    """Lấy palette để quantize ảnh (không cần trang).

    Trả về [] khi pixel_full_color = True → giữ nguyên màu gốc (không quantize).
    """
    if getattr(cfg, "pixel_full_color", False):
        return []  # rỗng => image_to_pixels giữ RGB gốc
    if cfg.pixel_palette_path and os.path.exists(cfg.pixel_palette_path):
        return load_palette_from_text(cfg.pixel_palette_path)
    return list(DEFAULT_PALETTE)


def generate_preview(cfg: Config, out_path: Optional[str] = None) -> str:
    """Sinh ảnh preview từ cfg.pixel_image_path. Trả về đường dẫn PNG."""
    palette = build_palette(cfg)
    cells = image_to_pixels(
        cfg.pixel_image_path, cfg.pixel_grid_w, cfg.pixel_grid_h, palette,
        dither=cfg.pixel_dither, bg_skip=cfg.pixel_bg_skip,
    )
    img = render_preview(cells, cfg.pixel_grid_w, cfg.pixel_grid_h)
    if not out_path:
        base = os.path.dirname(os.path.abspath(cfg.pixel_image_path))
        out_path = os.path.join(base, "pixel_preview.png")
    img.save(out_path, "PNG")
    return out_path


# ===========================================================================
# CLI
# ===========================================================================
def _parse_grid(s: str) -> tuple[int, int]:
    if "x" in s.lower():
        a, b = s.lower().split("x", 1)
        return int(a), int(b)
    n = int(s)
    return n, n


def main() -> None:
    p = argparse.ArgumentParser(
        description="Biến ảnh thành tranh pixel rồi tự vẽ lên canvas web."
    )
    p.add_argument("image", help="Đường dẫn ảnh nguồn")
    p.add_argument("--url", default="", help="URL trang pixel canvas")
    p.add_argument("--grid", default="100x100", help="Kích thước lưới WxH (vd 100x100)")
    p.add_argument("--cooldown", type=float, default=0.5, help="Giây chờ giữa mỗi ô")
    p.add_argument("--jitter", type=float, default=0.2, help="Nhiễu ± giây cho cooldown")
    p.add_argument("--palette", default="", help="File palette colors.txt (#RRGGBB/dòng)")
    p.add_argument("--dither", action="store_true", help="Bật Floyd-Steinberg dithering")
    p.add_argument("--bg-skip", action="store_true", help="Bỏ ô nền trắng/đen")
    p.add_argument("--smart-skip", action="store_true",
                   help="Chụp canvas, chỉ vẽ ô sai màu")
    p.add_argument("--preview", default="", help="Đường dẫn xuất PNG preview rồi thoát")
    p.add_argument("--dry-run", action="store_true",
                   help="Không mở trình duyệt, chỉ in danh sách ô")
    p.add_argument("--batch", type=int, default=0, help="Giới hạn số ô vẽ trong lần này")
    p.add_argument("--resume", default="", help="File pixel_progress.json để tiếp tục")
    p.add_argument("--headless", action="store_true")
    p.add_argument("--session", default="", help="Thư mục session Chrome")
    args = p.parse_args()

    gw, gh = _parse_grid(args.grid)

    # Trường hợp chỉ sinh preview.
    if args.preview:
        palette = load_palette_from_text(args.palette) if args.palette else list(DEFAULT_PALETTE)
        cells = image_to_pixels(args.image, gw, gh, palette, dither=args.dither, bg_skip=args.bg_skip)
        img = render_preview(cells, gw, gh)
        img.save(args.preview, "PNG")
        print(f"[Pixel] Đã lưu preview: {args.preview} ({len(cells)} ô).")
        return

    palette = load_palette_from_text(args.palette) if args.palette else list(DEFAULT_PALETTE)

    if args.resume and os.path.exists(args.resume):
        plan = PixelPlan.load(args.resume) or PixelPlan.from_image(_cli_cfg(args, gw, gh, palette), palette)
        print(f"[Pixel] Resume: {plan.index}/{len(plan.cells)} ô.")
    else:
        cells = image_to_pixels(args.image, gw, gh, palette, dither=args.dither, bg_skip=args.bg_skip)
        plan = PixelPlan(cells=cells, grid_w=gw, grid_h=gh, progress_path=_default_progress_path())
        print(f"[Pixel] Sẽ vẽ {len(cells)} ô.")

    if args.dry_run:
        for c in plan.cells[:50]:
            print(f"  ({c.x},{c.y}) rgb{c.rgb}")
        print(f"[Pixel][dry] dry-run xong ({len(plan.cells)} ô tổng). Không mở trình duyệt.")
        return

    # Mở trình duyệt.
    import browser as br
    cfg = _cli_cfg(args, gw, gh, palette)
    try:
        from config import app_dir
    except Exception:
        app_dir = lambda: os.path.dirname(os.path.abspath(__file__))  # type: ignore
    mgr = br.BrowserManager(cfg.session_dir or os.path.join(
        app_dir(), "session"), headless=args.headless)
    mgr.start()
    try:
        page = mgr.new_page()
        page.goto(args.url or cfg.pixel_url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(1500)
        geo = detect_canvas(page, cfg, print)
        if not geo:
            print("[Pixel][Lỗi] Không dò thấy canvas. Thoát.")
            return
        page_palette = detect_palette(page, cfg, print)
        paint(page, cfg, plan, page_palette, geo, log=print,
              batch_size=args.batch, dry_run=False)
        page.close()
    finally:
        mgr.close()


def _cli_cfg(args, gw: int, gh: int, palette) -> Config:
    cfg = Config()
    cfg.pixel_url = args.url
    cfg.pixel_grid_w = gw
    cfg.pixel_grid_h = gh
    cfg.pixel_cooldown_seconds = args.cooldown
    cfg.pixel_jitter_seconds = args.jitter
    cfg.pixel_palette_path = args.palette
    cfg.pixel_dither = args.dither
    cfg.pixel_bg_skip = args.bg_skip
    cfg.pixel_smart_skip = args.smart_skip
    cfg.pixel_image_path = args.image
    cfg.pixel_batch_size = args.batch
    cfg.session_dir = args.session
    return cfg


if __name__ == "__main__":
    main()
