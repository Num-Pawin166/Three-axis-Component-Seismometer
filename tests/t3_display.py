#!/usr/bin/env python3
"""
t3_display.py — ทดสอบจอ ST7796S
  1) เติมสีพื้นทีละสี  -> ดูว่าสีถูกต้องไหม (ถ้าแดง/น้ำเงินสลับ ให้แก้ TFT_BGR)
  2) ลายตารางและข้อความ -> ดูการวางตำแหน่งและฟอนต์
  3) วัดอัตราเฟรมจริง   -> ถ้าได้ 2-3 FPS แปลว่ายังไม่ได้ตั้ง spidev.bufsiz

รัน:  python3 tests/t3_display.py
"""
import _path  # noqa
from _guard import require_exclusive
import time

from PIL import Image, ImageDraw

import config as C
from drivers.st7796 import ST7796, load_font, font_has_thai

LINE = "-" * 62


def main():
    require_exclusive((C.TFT_PIN_DC, C.TFT_PIN_RST), "จอแสดงผล")
    print(f"เปิดจอ: SPI{C.TFT_BUS}.{C.TFT_DEV} ที่ {C.TFT_SPI_HZ/1e6:.0f} MHz "
          f"หมุน {C.TFT_ROTATION} องศา")
    tft = ST7796(bus=C.TFT_BUS, dev=C.TFT_DEV, speed_hz=C.TFT_SPI_HZ,
                 pin_dc=C.TFT_PIN_DC, pin_rst=C.TFT_PIN_RST,
                 rotation=C.TFT_ROTATION, invert=C.TFT_INVERT, bgr=C.TFT_BGR,
                 pin_bl=getattr(C, "TFT_PIN_BL", None))
    W, H = tft.width, tft.height
    print(f"ขนาดที่ใช้ได้: {W} x {H} พิกเซล")

    try:
        bl = getattr(C, "TFT_PIN_BL", None)
        print(f"\n{LINE}\n[0] ไฟส่องหลังจอ (backlight)\n{LINE}")
        if bl is None:
            print("   ไม่ได้ตั้ง TFT_PIN_BL — ถือว่าขา LED ต่อตรงเข้าไฟอยู่แล้ว")
        else:
            print(f"   คุมด้วย GPIO {bl}  — จะดับ 1 วินาทีแล้วติดกลับมา")
            print("   ถ้าจอไม่มืดลงเลย แปลว่าขา LED ไม่ได้ต่อกับ GPIO นี้จริง")
            tft.backlight(False); time.sleep(1.2)
            tft.backlight(True);  time.sleep(0.5)
            print("   ไฟกลับมาติดแล้ว")

        print(f"\n{LINE}\n[1] เติมสีพื้น — มองที่จอ\n{LINE}")
        for name, col in (("แดง", (255, 0, 0)), ("เขียว", (0, 255, 0)),
                          ("น้ำเงิน", (0, 0, 255)), ("ขาว", (255, 255, 255)),
                          ("ดำ", (0, 0, 0))):
            print(f"   กำลังแสดงสี{name}")
            tft.fill(col)
            time.sleep(0.6)
        print("   ถ้าสีแดงกับน้ำเงินสลับกัน ให้เปลี่ยน TFT_BGR ใน config.py")
        print("   ถ้าสีกลับด้านหมด (ขาวเป็นดำ) ให้เปลี่ยน TFT_INVERT")

        print(f"\n{LINE}\n[2] ลายตารางและข้อความ\n{LINE}")
        f_big, f_mid, f_sm = load_font(28), load_font(18), load_font(13)
        thai = font_has_thai(f_mid)
        print(f"   ฟอนต์ภาษาไทย: {'ใช้ได้' if thai else 'ไม่มี (จะแสดงเป็นกล่อง)'}")
        img = Image.new("RGB", (W, H), (10, 12, 18))
        d = ImageDraw.Draw(img)
        for x in range(0, W, 40):
            d.line([(x, 0), (x, H)], fill=(40, 46, 58))
        for y in range(0, H, 40):
            d.line([(0, y), (W, y)], fill=(40, 46, 58))
        d.rectangle([0, 0, W - 1, H - 1], outline=(255, 200, 60), width=2)
        for cx, cy, col in ((0, 0, (255, 80, 80)), (W - 1, 0, (80, 255, 120)),
                            (W - 1, H - 1, (110, 175, 255)), (0, H - 1, (255, 220, 90))):
            d.ellipse([cx - 9, cy - 9, cx + 9, cy + 9], fill=col)
        d.text((16, 14), "ST7796S", font=f_big, fill=(240, 244, 252))
        d.text((16, 52), f"{W} x {H}   {C.TFT_SPI_HZ/1e6:.0f} MHz", font=f_mid,
               fill=(160, 172, 196))
        d.text((16, 80), "ทดสอบภาษาไทย 0123456789" if thai
               else "Thai font missing - English fallback", font=f_mid, fill=(255, 220, 90))
        d.text((16, H - 26), "จุดกลมต้องอยู่ครบทั้ง 4 มุม" if thai
               else "All 4 corner dots must be visible", font=f_sm, fill=(140, 150, 170))
        tft.blit(img)
        print("   ดูที่จอ: ต้องเห็นจุดกลมครบทั้ง 4 มุม และกรอบสีเหลืองไม่ขาด")
        time.sleep(2.5)

        print(f"\n{LINE}\n[3] วัดอัตราเฟรม\n{LINE}")
        frames = 30
        t0 = time.perf_counter()
        for i in range(frames):
            im = Image.new("RGB", (W, H), (i * 8 % 256, 30, 120))
            dd = ImageDraw.Draw(im)
            dd.text((20, H // 2 - 20), f"frame {i+1}/{frames}", font=f_big,
                    fill=(255, 255, 255))
            tft.blit(im)
        dt = time.perf_counter() - t0
        fps = frames / dt
        print(f"   {frames} เฟรม ใน {dt:.2f} วินาที  ->  {fps:.1f} FPS")
        print(f"   ข้อมูลต่อเฟรม {W*H*2:,} ไบต์")
        if fps < 5:
            print("   !! ช้าผิดปกติ — น่าจะยังไม่ได้ตั้ง spidev.bufsiz=65536 "
                  "ใน /boot/firmware/cmdline.txt")
        else:
            print("   ความเร็วปกติ (คาดหวังราว 10-12 FPS ที่ 40 MHz)")

        tft.fill((0, 0, 0))
        print("\nจบการทดสอบจอ")
    finally:
        tft.close()
        try:
            from gpiozero import Device
            if Device.pin_factory is not None:
                Device.pin_factory.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()