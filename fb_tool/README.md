# Auto Check-in Facebook + Messenger (tool độc lập)

Tự động comment + Like trên trang Facebook theo mẫu `[giờ:phút] N[ngày].[tháng].[năm] LVT`,
và gửi ảnh từng trang PDF vào Messenger.

## Cài đặt (1 lần)

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

## Chạy

```bash
python main_fb.py
```

## Cách dùng

1. Nhập link trang FB, người nhận Messenger, chọn PDF, đặt lịch.
2. Bấm **🔑 Đăng nhập FB** → đăng nhập Facebook → **đóng Chrome** để lưu phiên.
3. Bấm **▶ BẮT ĐẦU CHẠY** → tự chạy theo lịch.

Các ô **link trang** và **người nhận** để trống lần đầu — tự nhập khi dùng.
Cấu hình tự lưu khi đóng app (mở lại không phải nhập lại).

> ⚠️ Tự động hóa Facebook vi phạm Điều khoản dịch vụ của Facebook, rủi ro tự chịu.
