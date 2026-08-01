"""Render từng trang PDF ra ảnh PNG, theo dõi trang hiện tại."""
from __future__ import annotations

import os
import tempfile

import fitz  # PyMuPDF


class PdfPager:
    """Quản lý việc render lần lượt từng trang PDF."""

    def __init__(self, pdf_path: str, start_page: int = 1):
        self.pdf_path = pdf_path
        self.current = max(1, start_page)   # trang kế cần gửi (bắt đầu từ 1)
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"Không tìm thấy file PDF: {pdf_path}")

    @property
    def page_count(self) -> int:
        with fitz.open(self.pdf_path) as doc:
            return doc.page_count

    def has_more(self) -> bool:
        return self.current <= self.page_count

    def render_current(self, dpi: int = 150) -> str:
        """Render trang `current` ra file PNG tạm, trả về đường dẫn ảnh."""
        if self.current > self.page_count:
            raise IndexError(f"Đã hết PDF (tổng {self.page_count} trang).")
        with fitz.open(self.pdf_path) as doc:
            page = doc[self.current - 1]
            zoom = dpi / 72
            matrix = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=matrix)
            tmp = tempfile.NamedTemporaryFile(
                suffix="_page.png", delete=False, prefix=f"pdf_p{self.current}_"
            )
            tmp.close()
            pix.save(tmp.name)
            return tmp.name

    def advance(self) -> None:
        """Tăng con trỏ trang lên +1 cho lần gửi kế tiếp."""
        self.current += 1

    def reset(self, start_page: int = 1) -> None:
        self.current = max(1, start_page)
