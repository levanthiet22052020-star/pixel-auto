# 🎨 Auto Pixel Painter — DOM mode + Humanize

Tự động vẽ tranh pixel art lên canvas pixel công cộng (`datn.unifolio.io.vn/pixel`). Tool tự đăng nhập, tự dò kích thước canvas, vẽ theo **nét (batch) + jitter ngẫu nhiên** để mô phỏng hành vi người thật — tránh bị server flag/khóa tài khoản.

---

## ✨ Tính năng chính

| Tính năng | Mô tả |
|-----------|-------|
| 🖼 **Pixel Painter (DOM mode)** | Tô ảnh pixel lên canvas chung qua Playwright (click DOM thật, không cần điều khiển chuột vật lý) |
| 🔍 **Auto-detect grid** | Tự dò kích thước canvas thật (512×320, cell 4px) bằng auto-correlation — không cần hardcode |
| 🛡 **Humanize (chống khóa)** | Vẽ theo **nét 3-12 ô** + jitter ngẫu nhiên + nghỉ siêu dài thỉnh thoảng → server không phát hiện bot |
| 🧩 **Patch anti-bot** | Vô hiệu hóa DevTools detection (module 87105) + xử lý overlay "Nội dung đang được bảo vệ" |
| 👥 **Đa tài khoản song song** | Mỗi acc 1 Chrome + session + tiến độ riêng, tự chia dải cột, không đè nhau |
| 🎯 **Smart verify** | So sánh before/after để chống false-negative do web **làm tròn màu** (quantize) |
| ⏯ **Resume** | Lưu tiến độ từng acc, mở lại chạy tiếp từ ô chưa vẽ |
| 🖥 **GUI Tkinter** | Giao diện đồ họa + xem preview vị trí ảnh trên canvas |

---

## 📦 Cài đặt

```bash
# 1. Cài dependencies
pip install -r requirements.txt
python -m playwright install chromium

# 2. Tạo config từ template (KHÔNG commit config.yaml)
copy config.example.yaml config.yaml      # Windows
cp config.example.yaml config.yaml        # Linux/Mac

# 3. Mở config.yaml, điền tài khoản + mật khẩu + đường dẫn ảnh
notepad config.yaml                        # Windows
nano config.yaml                           # Linux/Mac
```

> Yêu cầu: Python 3.10+, Chrome cài sẵn trên máy.

---

## 🚀 Chạy

```bash
python main.py
```

→ Mở cửa sổ GUI → nhập ảnh, tài khoản → bấm **▶ Vẽ tất cả** hoặc **👥 Vẽ đa tài khoản**.

---

## 🎯 Hướng dẫn dùng nhanh (DOM mode)

### 1 tài khoản
1. Mở app → mục **Ảnh nguồn** → **Chọn ảnh...** → bấm **🖼 Xem preview** để canh vị trí.
2. Mục **Đăng nhập (DOM)** → nhập URL trang chính + tài khoản + mật khẩu.
3. Mục **Kích thước** → đặt **Rộng/Cao ảnh (ô)** + **Vẽ từ ô X/Y** (góc trên-trái trên canvas).
4. Bấm **▶ Vẽ thử (mẻ)** để test vài ô, rồi **▶ Vẽ tất cả**.

### Nhiều tài khoản (song song)
1. Mục **Đa tài khoản** → bấm **➕ Thêm tài khoản** cho mỗi acc phụ.
2. Bấm **👥 Vẽ đa tài khoản** → tool mở N Chrome song song, mỗi acc tô 1 dải cột.

> Mỗi acc có rate-limit riêng **600 ô/5 phút**. Acc nào hết quota tự đợi, acc khác vẫn chạy.

---

## 🛡 Chế độ Humanize (chống flag/khóa)

Web `datn` có cơ chế server-side phát hiện automation. Nếu vẽ quá đều/tuần tự/nhanh → bị **flagged** → **khóa tài khoản** theo cấp độ tăng dần:

```
[30 phút → 1 giờ → 3 giờ → 6 giờ → 12 giờ → 1 ngày → 3 ngày → 7 ngày]
```

Bật `pixel_humanize: true` (mặc định) để mô phỏng người thật:

| Tham số | Mặc định | Ý nghĩa |
|---------|----------|---------|
| `pixel_stroke_min` / `pixel_stroke_max` | 3 / 12 | Số ô trong 1 nét vẽ (kéo chuột) |
| `pixel_stroke_cell_min` / `pixel_stroke_cell_max` | 0.1 / 0.4 | Nghỉ giữa các ô trong nét (giây) |
| `pixel_stroke_gap_min` / `pixel_stroke_gap_max` | 2.0 / 8.0 | Nghỉ giữa các nét (giây) — người xem ảnh |
| `pixel_long_break_chance` | 0.10 | Xác suất nghỉ siêu dài (10%) |
| `pixel_long_break_min` / `pixel_long_break_max` | 15 / 45 | Nghỉ siêu dài (giây) — giống đi làm việc khác |

**Tốc độ**: ~1.5s/ô (so với 0.5s/ô khi tắt). Ảnh 100×80 (8,000 ô) = ~3.3 giờ/acc.

> ⚠️ Khi chạy, **không mở DevTools (F12)** — web phát hiện qua `outerWidth - innerWidth > 160`. Tool đã patch nhưng tốt nhất tránh.

---

## ⚙️ Cấu hình `config.yaml`

Xem template đầy đủ trong [`config.example.yaml`](config.example.yaml). Các mục quan trọng:

```yaml
pixel_url: https://datn.unifolio.io.vn/pixel
pixel_username: PS43933            # tài khoản DATN
pixel_password: 'YOUR_PASSWORD'
pixel_image_path: ./anh.png        # ảnh cần vẽ

pixel_grid_w: 512                  # canvas thật site datn
pixel_grid_h: 320
pixel_offset_x: 192                # vẽ từ ô (192, 60)
pixel_offset_y: 60

pixel_smart_skip: false            # false = ép vẽ lại tất cả (đè ảnh cũ)
pixel_humanize: true               # chống flag/khóa

# Đa tài khoản: "user1|pass1;user2|pass2;user3|pass3"
pixel_multi_accounts: 'PS44335|pass2;PS44235|pass3'
pixel_num_accounts: 3
```

---

## 🧠 Cơ chế kỹ thuật

### Auto-detect grid (`dom_painter.py`)
Canvas site datn là `<canvas width="2048" height="1280">` = lưới 512×320 ô, mỗi ô 4px. Tool tự dò bằng **auto-correlation**: lấy nhiều dòng pixel, với mỗi cell size ứng viên [4,6,8,3,5,10,12,16], đếm số pixel[x] ≈ pixel[x+step]. Cell thật = step có **ratio cao nhất tuyệt đối**.

### Verify before/after (`verify_cell`)
Web **làm tròn màu** (quantize): set `(255,0,0)` → lưu `(212,32,39)`. So sánh với màu set sẽ false-negative. Tool đọc màu ô **trước và sau** khi vẽ → nếu đổi ≥25 = thành công.

### API endpoint thật
```
POST /api/community-pixels
Body: {"changes":[{"x":482,"y":315,"color":"#FF0000"}],
       "activityContext":{"tool":"pencil","brushSize":1,
                          "mirrorHorizontal":false,"mirrorVertical":false}}
Response: {"remaining":599,"retryAfterSeconds":300,
           "activity":{"flagged":false,"warningReason":null}}
```

Tool không POST trực tiếp — nó **click DOM thật** (mouse down/up) để web tự build activityContext → giống người dùng thật nhất.

---

## 📁 Cấu trúc dự án

```
auto-checkin-fb/
├── main.py                  # vào chương trình
├── gui.py                   # giao diện Tkinter
├── config.py                # đọc/ghi config.yaml
├── config.example.yaml      # template config (KHÔNG commit config.yaml)
├── browser.py               # quản lý Chrome + phiên Playwright
│
├── dom_painter.py           # ⭐ vẽ pixel DOM mode + humanize + anti-detection
├── pixel_painter.py         # ảnh → pixel + smart skip + palette
├── screen_painter.py        # vẽ qua chuột thật (screen mode, ít dùng)
│
├── worker_cli.py            # worker đa tài khoản (chạy trong subprocess)
├── multi_account.py         # điều phối N worker song song
├── multi_painter.py         # multi-account cũ (CLI)
│
├── pixel_tool/              # tool pixel standalone
├── requirements.txt
└── README.md
```

---

## 🔒 Bảo mật

- `config.yaml` và `accounts.yaml` **đã trong `.gitignore`** — chứa mật khẩu, KHÔNG commit.
- Dùng `config.example.yaml` làm template, điền mật khẩu của bạn vào bản copy.
- Mật khẩu chỉ lưu local trên máy bạn, không gửi đi đâu ngoài trang đích.

---

## ⚠️ Rủi ro & chịu trách nhiệm

Tự động hóa có thể vi phạm Điều khoản dịch vụ của trang đích. Web có cơ chế:
- **Flag** thao tác bất thường → cảnh báo toast
- **Khóa** tài khoản theo cấp độ (30 phút → 7 ngày)
- **Silent reject** ô đang bị người khác tranh chấp

Tool đã có humanize + anti-detection, nhưng **không đảm bảo 100%** không bị phát hiện. Dùng cho mục đích cá nhân, rủi ro tự chịu.

---

## 📝 License

Cá nhân — dùng nội bộ.
