# Pixel Painter (tool độc lập)

Biến ảnh thường thành tranh pixel rồi tự vẽ lên canvas pixel công cộng.

## Chạy bằng file exe (đã build)

```
dist/PixelPainter/PixelPainter.exe   ← double-click để chạy
```

- Cấu hình, tiến độ tô màu, session đăng nhập đều lưu **cạnh file exe**
  (trong thư mục `dist/PixelPainter/`).
- **Đóng app → mở lại → chạy tiếp**, không vẽ lại từ đầu (tiến độ tự lưu sau mỗi ô).
- Các ô URL/tài khoản/mật khẩu **để trống** lần đầu — tự nhập khi dùng.

## Chạy bằng Python (dev)

```bash
pip install -r requirements.txt
python -m playwright install chromium   # chỉ cần nếu không có Chrome thật
python main_pixel.py
```

## Build lại exe

```bash
pip install pyinstaller
pyinstaller pixel_tool.spec --noconfirm --clean
# kết quả: dist/PixelPainter/PixelPainter.exe
```

---

## Multi-account: nhiều acc vẽ song song

Mở nhiều tài khoản datn.unifolio.io.vn cùng lúc, mỗi acc vẽ một **dải cột** của
cùng một bức tranh → chạy song song, vượt quota 120 ô/5 phút của 1 acc.

> ⚠️ **Rủi ro**: server có thể gộp rate-limit theo IP. Nếu tất cả acc dùng chung 1
> IP, throughput không tăng → **khuyến nghị dùng proxy khác IP mỗi acc** (tool hỗ
> trợ sẵn). Vi phạm ToS của trang, rủi ro tự chịu.

### 1) Cấu hình `accounts.yaml`

File `accounts.yaml` (đã có sẵn template) định nghĩa ảnh + danh sách tài khoản:
```yaml
image: starry_small.png        # ảnh nguồn (để cạnh exe)
grid: 100x100
smart_skip: true

accounts:
  - name: acc1
    session_dir: ""            # trống = app_dir/session/acc1
    username: "MSSV1"
    password: "pass1"
    proxy: "http://user:pass@1.2.3.4:8080"   # tuỳ chọn
    x_start: 0                 # bỏ trống + --auto-split để tự chia đều
    x_end: 49
  - name: acc2
    x_start: 50
    x_end: 99
```

### 2) Dùng (CLI)

```bash
# Login lần đầu từng acc (mở Chrome → tự đăng nhập datn → ĐÓNG Chrome)
python multi_painter.py setup acc1 --config accounts.yaml
python multi_painter.py setup acc2 --config accounts.yaml

# Vẽ song song (dải cột như trong config)
python multi_painter.py paint --config accounts.yaml

# Tự chia đều grid_w cột cho N acc
python multi_painter.py paint --config accounts.yaml --auto-split

# Chỉ chạy 1 acc để debug (không vẽ thật)
python multi_painter.py paint --config accounts.yaml --account acc1 --dry-run

# Xoá tiến độ, vẽ lại từ đầu
python multi_painter.py paint --config accounts.yaml --reset
```

### 3) Đặc điểm

- **Chia cột (x)**: mỗi acc phụ trách 1 dải cột dọc, không chồng lấp.
- **Resume riêng**: tiến độ từng acc lưu trong `progress_multi/<name>.json` (cạnh
  exe). Đóng/mở lại bấm paint là **tiếp tục**.
- **Auto login lại**: nếu session hết hạn, worker tự đăng nhập bằng
  `username`/`password` trong config.
- **Log tổng**: in tiến độ tất cả acc mỗi 5 giây.
- **Ctrl+C**: dừng tất cả worker an toàn, lưu tiến độ.

---

## Lưu ý quan trọng về dữ liệu

- `config.yaml` — cấu hình (URL, tài khoản, vị trí canh canvas...)
- `accounts.yaml` — cấu hình multi-account (nhiều acc vẽ song song)
- `pixel_progress.json` — tiến độ tô màu đơn acc (tự lưu sau mỗi ô → resume được)
- `progress_multi/` — tiến độ từng acc khi chạy multi-account (1 file/acc)
- `session/` — phiên đăng nhập Chrome

Cả đều nằm cạnh exe → **không bị mất khi tắt máy**. Nhờ vậy đóng/mở lại tool
vẫn tiếp tục vẽ từ ô dừng, không phải làm lại từ đầu.
