"""Region picker — chọn một vùng chữ nhật trên màn hình bằng kéo-thả chuột.

Mở một cửa sổ overlay fullscreen trong suốt, người dùng kéo chuột chọn vùng
(giống Snipping Tool). Trả về toạ độ vật lý (x1, y1, x2, y2) góc trên-trái và
dưới-phải.

Dùng cho screen mode calibration — chính xác hơn click-2-lần vì không bị dialog
messagebox chiếm focus.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import sys
import threading
import tkinter as tk

from screen_painter import screen_size


def pick_region(title: str = "Kéo chuột để chọn vùng") -> tuple[int, int, int, int] | None:
    """Hiển thị overlay, trả về (x1,y1,x2,y2) hoặc None nếu bỏ qua.

    Chạy Tkinter mainloop trong thread nền để không block GUI chính.
    """
    result: dict[str, object] = {"box": None}

    def run():
        sw, sh = screen_size()
        root = tk.Toplevel()
        root.title(title)
        root.attributes("-fullscreen", True)
        root.attributes("-alpha", 0.25)          # mờ để nhìn thấy màn hình bên dưới
        root.attributes("-topmost", True)
        root.configure(bg="black", cursor="crosshair")
        root.geometry(f"{sw}x{sh}+0+0")

        canvas = tk.Canvas(root, highlightthickness=0, bg="black")
        canvas.pack(fill="both", expand=True)

        # hướng dẫn
        canvas.create_text(
            sw // 2, 30,
            text=f"{title}  —  ESC để bỏ qua",
            fill="white", font=("Segoe UI", 16, "bold"),
        )

        start = {"x": None, "y": None}
        rect_id = {"id": None}

        def on_press(e):
            start["x"], start["y"] = e.x_root, e.y_root
            if rect_id["id"]:
                canvas.delete(rect_id["id"])

        def on_drag(e):
            if start["x"] is None:
                return
            x1, y1 = start["x"], start["y"]
            x2, y2 = e.x_root, e.y_root
            if rect_id["id"]:
                canvas.delete(rect_id["id"])
            rect_id["id"] = canvas.create_rectangle(
                x1, y1, x2, y2, outline="#00e5ff", width=3, fill="#00e5ff",
                stipple="gray50",
            )

        def on_release(e):
            if start["x"] is None:
                return
            x1, y1 = start["x"], start["y"]
            x2, y2 = e.x_root, e.y_root
            x1, x2 = sorted((x1, x2))
            y1, y2 = sorted((y1, y2))
            if abs(x2 - x1) > 3 and abs(y2 - y1) > 3:
                result["box"] = (x1, y1, x2, y2)
            root.destroy()

        def on_key(e):
            if e.keysym == "Escape":
                root.destroy()

        canvas.bind("<ButtonPress-1>", on_press)
        canvas.bind("<B1-Motion>", on_drag)
        canvas.bind("<ButtonRelease-1>", on_release)
        root.bind("<Escape>", on_key)
        root.focus_force()
        root.mainloop()

    t = threading.Thread(target=run, daemon=False)
    t.start()
    t.join()
    return result["box"]  # type: ignore[return-value]
