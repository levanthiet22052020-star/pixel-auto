"""Chuyển Starry Night -> pixel art 384x240 dung lươu 24 màu web, xuất JSON cells."""
import json
import os
from PIL import Image

# Đường dẫn tương đối: dùng thư mục chứa file .py này (không hardcode máy ai).
_DIR = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(_DIR, "starry_source.jpg")  # ← đặt ảnh nguồn ở đây
OUT_JSON = os.path.join(_DIR, "starry_cells.json")
OUT_PREVIEW = os.path.join(_DIR, "starry_preview.png")
OUT_RAW = os.path.join(_DIR, "starry_small.png")

# 24 màu chính xác của web datn.unifolio.io.vn/pixel
palette_hex = ["111827","374151","64748B","CBD5E1","EF4444","F43F5E","F97316",
               "FACC15","A3E635","22C55E","10B981","14B8A6","06B6D4","0EA5E9",
               "3B82F6","6366F1","8B5CF6","A855F7","EC4899","F472B6","7C2D12",
               "92400E","FDE68A","FFFFFF"]
pal_rgb = [(int(h[0:2],16),int(h[2:4],16),int(h[4:6],16)) for h in palette_hex]

# LUT khoảng cách Euclidean tới 24 màu
def nearest(rgb):
    r,g,b = rgb
    best_i, best_d = 0, 1e18
    for i,(pr,pg,pb) in enumerate(pal_rgb):
        d = (r-pr)*(r-pr)+(g-pg)*(g-pg)+(b-pb)*(b-pb)
        if d < best_d:
            best_d, best_i = d, i
    return best_i

img = Image.open(SRC).convert("RGB")
w,h = img.size
print("src:", w, h)

# Crop đúng tỷ lệ 384:240 = 1.6 (giữ full height, cắt width)
target_ratio = 384/240.0
cur_ratio = w/h
if cur_ratio > target_ratio:
    new_w = int(h*target_ratio)
    left = (w-new_w)//2
    cropped = img.crop((left,0,left+new_w,h))
else:
    new_h = int(w/target_ratio)
    top = (h-new_h)//2
    cropped = img.crop((0,top,w,top+new_h))
print("cropped:", cropped.size)

# Resize giữ nguyên 384x240 (độ phân giải đầy đủ)
small = cropped.resize((384,240), Image.LANCZOS)
small.save(OUT_RAW)
print("saved raw:", OUT_RAW)

pixels = list(small.getdata())  # 384*240 = 92160 pixels

# Map mỗi pixel -> index màu gần nhất
cells = []
counts = [0]*len(pal_rgb)
for idx,(r,g,b) in enumerate(pixels):
    gx = idx % 384
    gy = idx // 384
    ci = nearest((r,g,b))
    cells.append([gx,gy,ci])
    counts[ci]+=1

# Bỏ qua ô trắng (nền) để đỡ vẽ nhiều -> ta giữ lại nhưng đánh dấu, ở đây giữ hết
# Lưu JSON
with open(OUT_JSON,"w") as f:
    json.dump({"w":384,"h":240,"palette":pal_rgb,"cells":cells}, f)
print("saved json:", OUT_JSON, "cells:", len(cells))

# Thống kê màu
for hex_,cnt in sorted(zip(palette_hex,counts), key=lambda x:-x[1]):
    if cnt: print(f"  #{hex_}: {cnt}")

# Preview quantize
prev = Image.new("RGB",(384,240))
for i,(r,g,b) in enumerate([pal_rgb[c[2]] for c in cells]):
    prev.putpixel((i%384,i//384),(r,g,b))
prev.resize((768,480), Image.NEAREST).save(OUT_PREVIEW)
print("saved preview:", OUT_PREVIEW)
