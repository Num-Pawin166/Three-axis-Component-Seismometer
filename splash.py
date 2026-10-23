#!/usr/bin/env python3
"""
splash.py — ขึ้นโลโก้บนจอระหว่างรอระบบบูต

ทำไมจอถึงขาวตอนเปิดเครื่อง
    พาเนล ST7796S พอได้ไฟเลี้ยงจะสว่างขึ้นมาเลย แต่ยังไม่มีใครส่งภาพไปให้
    หน่วยความจำภาพในตัวจอจึงเป็นค่าสุ่มซึ่งมักออกมาเป็นสีขาว
    จะมีภาพได้ต้องมีโปรแกรมสั่งผ่าน SPI ซึ่งต้องรอให้ลินุกซ์บูตถึงจุดหนึ่งก่อน

วิธีกำจัดจอขาวทำสองขั้น
    1. ดับไฟส่องหลังตั้งแต่เฟิร์มแวร์ ด้วยการใส่บรรทัดนี้ใน config.txt
           gpio=22=op,dl
       ขานี้จะถูกตั้งเป็นขาออกและดึงลงต่ำตั้งแต่ก่อนลินุกซ์เริ่มทำงาน
       จอจึงมืดสนิท ไม่เห็นสีขาวเลย
    2. ให้ไฟล์นี้ทำงานทันทีที่ SPI พร้อม วาดโลโก้ แล้วค่อยเปิดไฟส่องหลัง
       ผู้ใช้จะเห็นจอดำ -> โลโก้ -> หน้าจอโปรแกรมจริง ไม่มีจังหวะขาวแวบ

วางไฟล์ชื่อ logo.png (หรือ .jpg .bmp .gif .webp) ไว้ข้าง ๆ ไฟล์นี้
จะเอารูปนั้นมาแสดงให้เอง รองรับพื้นหลังโปร่งใส
ถ้าไม่มีไฟล์ จะวาดสัญลักษณ์แทนให้

รัน:  python3 splash.py                 แสดงโลโก้แล้วค้างไว้
      python3 splash.py --text "ชื่อ"   เปลี่ยนข้อความ
      python3 splash.py --logo รูป.png  เลือกไฟล์โลโก้เอง
      python3 splash.py --light         พื้นขาว (สำหรับโลโก้ที่เป็นตัวเข้ม)
      python3 splash.py --bake          เตรียมภาพดิบไว้ให้ splash_boot.py ใช้ตอนบูต
      python3 splash.py --off           ล้างจอเป็นดำแล้วดับไฟส่องหลัง
      python3 splash.py --preview a.png บันทึกเป็นไฟล์ภาพแทนการส่งขึ้นจอ
"""
import os
import sys
import time

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import config as C                                    # noqa: E402
from drivers.st7796 import ST7796, load_font          # noqa: E402

# วางไฟล์โลโก้ชื่อใดชื่อหนึ่งข้างล่างนี้ไว้ในโฟลเดอร์เดียวกับไฟล์นี้
# หรือจะสั่ง --logo <ที่อยู่ไฟล์> ตอนรันก็ได้
LOGO_NAMES = ("logo.png", "logo.jpg", "logo.jpeg", "logo.bmp",
              "logo.gif", "logo.webp")


def find_logo(given=None):
    if given:
        return given if os.path.exists(given) else None
    for nm in LOGO_NAMES:
        p = os.path.join(HERE, nm)
        if os.path.exists(p):
            return p
    return None
TITLE = "เครื่องวัดแรงสั่นสะเทือน 3 แกน"
SUB = "Three-axis Component Seismometer"
FOOT = "กำลังเริ่มระบบ..."

BG = (10, 12, 18)
FG = (236, 240, 248)
BG_LIGHT = (248, 249, 252)      # ใช้กับโลโก้ที่เป็นตัวเข้มบนพื้นขาว
FG_LIGHT = (24, 28, 38)
ACCENT = (255, 212, 92)
DIM = (120, 132, 155)


def draw_mark(d, cx, cy, r):
    """วาดสัญลักษณ์คลื่นสั่นสะเทือนเมื่อไม่มีไฟล์โลโก้

    วงกลมซ้อนกันสามวงแทนคลื่นที่แผ่ออก และจุดตรงกลางแทนจุดกำเนิด
    """
    for i, rr in enumerate((r, r * 0.68, r * 0.36)):
        shade = 70 + i * 60
        d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr],
                  outline=(shade, shade + 40, shade + 70), width=3)
    d.ellipse([cx - 6, cy - 6, cx + 6, cy + 6], fill=ACCENT)
    # แกนสามเส้นแทนสามแกนที่วัด
    for dx, dy in ((0, -1), (0.87, 0.5), (-0.87, 0.5)):
        d.line([(cx, cy), (cx + dx * r * 1.22, cy + dy * r * 1.22)],
               fill=(90, 150, 220), width=2)


def build(W, H, text=None, logo=None, light=False):
    """สร้างภาพโลโก้ คืน PIL Image ขนาดเท่าจอ"""
    bg = BG_LIGHT if light else BG
    fg = FG_LIGHT if light else FG
    img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img)
    f_big, f_mid, f_sm = load_font(26), load_font(16), load_font(13)

    art = None
    path = find_logo(logo)
    if path:
        try:
            art = Image.open(path)
            if art.mode in ("RGBA", "LA", "P"):
                # โลโก้ที่มีพื้นหลังโปร่งใส ต้องผสมกับสีพื้นก่อน
                # ไม่งั้นส่วนโปร่งจะกลายเป็นดำสนิทเป็นกรอบสี่เหลี่ยมรอบโลโก้
                art = art.convert("RGBA")
                base = Image.new("RGBA", art.size, bg + (255,))
                art = Image.alpha_composite(base, art).convert("RGB")
            else:
                art = art.convert("RGB")
        except Exception as e:
            print(f"เปิดไฟล์โลโก้ไม่ได้ ({path}): {e}", flush=True)
            art = None

    if art is not None:
        # ย่อให้พอดีจอโดยคงสัดส่วน แล้ววางกลาง เหลือที่ข้างล่างไว้ใส่ข้อความ
        box_w, box_h = int(W * 0.80), int(H * 0.54)
        art.thumbnail((box_w, box_h), Image.LANCZOS)
        img.paste(art, ((W - art.width) // 2, int(H * 0.09)))
        ty = int(H * 0.09) + art.height + 14
    else:
        draw_mark(d, W // 2, int(H * 0.34), int(H * 0.19))
        ty = int(H * 0.34) + int(H * 0.19) + 26

    title = text if text else TITLE
    if title:
        tw = d.textlength(title, font=f_big)
        # ถ้ารูปสูงจนข้อความจะล้นจอ ให้ข้ามข้อความไป โลโก้สำคัญกว่า
        if ty + 30 < H - 30:
            d.text(((W - tw) / 2, ty), title, font=f_big, fill=fg)
            ty += 34
    if ty + 20 < H - 30:
        tw = d.textlength(SUB, font=f_mid)
        d.text(((W - tw) / 2, ty), SUB, font=f_mid, fill=DIM)

    tw = d.textlength(FOOT, font=f_sm)
    d.text(((W - tw) / 2, H - 26), FOOT, font=f_sm, fill=(90, 100, 120))
    return img


def open_tft():
    return ST7796(bus=C.TFT_BUS, dev=C.TFT_DEV, speed_hz=C.TFT_SPI_HZ,
                  pin_dc=C.TFT_PIN_DC, pin_rst=C.TFT_PIN_RST,
                  rotation=C.TFT_ROTATION, invert=C.TFT_INVERT, bgr=C.TFT_BGR,
                  pin_bl=getattr(C, "TFT_PIN_BL", None))


def main():
    args = sys.argv[1:]

    def opt(name, default=None):
        if name in args:
            i = args.index(name)
            if i + 1 < len(args):
                return args[i + 1]
        return default

    text = opt("--text")
    logo = opt("--logo")
    light = "--light" in args
    if logo and not os.path.exists(logo):
        print(f"ไม่พบไฟล์โลโก้: {logo}")
        return 2
    found = find_logo(logo)
    print("โลโก้ที่ใช้: " + (found if found else "ไม่มีไฟล์ จะวาดสัญลักษณ์ให้แทน"),
          flush=True)

    if "--bake" in args:
        # แปลงภาพเป็นไบต์ RGB565 เก็บไว้ล่วงหน้า
        # ตอนบูต splash_boot.py จะได้แค่เปิดไฟล์แล้วเทลงจอ ไม่ต้องคำนวณอะไรเลย
        W, H = (480, 320) if C.TFT_ROTATION in (90, 270) else (320, 480)
        img = build(W, H, text, logo, light)
        out = os.path.join(HERE, "splash.raw")
        with open(out, "wb") as f:
            f.write(ST7796.to565(img))
        print(f"เตรียมภาพดิบไว้ที่ {out}  ({os.path.getsize(out):,} ไบต์)")
        print("ตอนบูตให้ service เรียก splash_boot.py แทน splash.py")
        return 0

    if "--preview" in args:
        out = opt("--preview", "splash.png")
        W, H = (480, 320) if C.TFT_ROTATION in (90, 270) else (320, 480)
        build(W, H, text, logo, light).save(out)
        print(f"บันทึกตัวอย่างไว้ที่ {out}")
        return 0

    # ตอนบูต ไฟล์นี้อาจถูกเรียกก่อนที่เคอร์เนลจะสร้าง /dev/spidev* เสร็จ
    # จึงรอสักพักแทนที่จะยอมแพ้ทันที
    dev = f"/dev/spidev{C.TFT_BUS}.{C.TFT_DEV}"
    for _ in range(40):                       # รอไม่เกิน 20 วินาที
        if os.path.exists(dev):
            break
        time.sleep(0.5)

    tft, first_err = None, None
    for attempt in range(10):                 # เผื่อขายังถูกจองค้างอยู่
        try:
            tft = open_tft()
            break
        except Exception as e:
            if first_err is None:
                first_err = e                 # เก็บตัวแรกไว้ ตัวหลังมักเป็นผลพวง
            time.sleep(1.0)
    if tft is None:
        print(f"เปิดจอไม่ได้: {first_err}", flush=True)
        if "busy" in str(first_err).lower() or "in use" in str(first_err).lower():
            print("   มีโปรแกรมอื่นถือจออยู่ (แอปหลักหรือ service)", flush=True)
            print("   สั่ง  ./stop.sh  ก่อน แล้วรันใหม่", flush=True)
        return 1

    try:
        if "--off" in args:
            tft.fill((0, 0, 0))
            tft.backlight(False)
            print("ล้างจอและดับไฟส่องหลังแล้ว")
            return 0

        # ลำดับสำคัญ: ส่งภาพให้ครบก่อน แล้วค่อยเปิดไฟ
        # ถ้าเปิดไฟก่อน จะเห็นภาพเก่าหรือสีขาวแวบหนึ่งก่อนโลโก้จะขึ้น
        tft.backlight(False)
        tft.blit(build(tft.width, tft.height, text, logo, light))
        tft.backlight(True)
        print("แสดงโลโก้แล้ว", flush=True)
        return 0
    finally:
        # ปิดเฉพาะ SPI กับขา GPIO ไม่ล้างจอ ภาพจะค้างอยู่จนโปรแกรมหลักมาวาดทับ
        try:
            tft.spi.close()
        except Exception:
            pass
        for obj in (tft.dc, tft.rst, tft.bl):
            if obj is not None:
                try:
                    obj.close()
                except Exception:
                    pass
        # พอปล่อยขา gpiozero จะคืนขาเป็นขาอ่าน ไฟส่องหลังอาจดับตามไปด้วย
        # จึงสั่งค้างไว้เป็นขาออกระดับสูงด้วย pinctrl ภาพจะติดอยู่จนแอปหลักมารับช่วง
        bl = getattr(C, "TFT_PIN_BL", None)
        if bl is not None and "--off" not in args:
            os.system(f"pinctrl set {int(bl)} op dh >/dev/null 2>&1")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)