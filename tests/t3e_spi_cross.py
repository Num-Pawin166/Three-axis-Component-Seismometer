#!/usr/bin/env python3
"""
t3e_spi_cross.py — แยกให้ชัดว่า "การใช้บัส SPI0" ทำให้จอตายหรือเปล่า

สิ่งที่รู้แล้ว
  - จอทำงานปกติเมื่ออยู่ลำพัง และเมื่อมีทัชสกรีนด้วย
  - การกระตุกขา GPIO ของ ADC (RESET/START/DRDY) ไม่ทำให้จอเป็นอะไร
  - แต่พอเธรด ADC ทำงานเต็มรูปแบบ จอขาวทันที

เธรดนั้นทำเพิ่มอย่างเดียวคือเปิด /dev/spidev0.0 แล้วรับส่งข้อมูล
สคริปต์นี้จึงทดสอบทีละชิ้นโดยไม่วาดจอซ้ำเลย ถ้าภาพหายตอนไหน ชิ้นนั้นคือต้นเหตุ

ถ้าการใช้บัส SPI0 ล้วน ๆ ทำให้จอตาย แปลว่ามีสายของบอร์ด ADC
ไปเสียบโดนขาของบัส SPI1 เข้า ทำให้สองบัสตีกัน

รัน:  python3 tests/t3e_spi_cross.py
"""
import _path  # noqa
from _guard import require_exclusive
import time

import spidev
from PIL import Image, ImageDraw

import config as C
from drivers.st7796 import ST7796, load_font

PAUSE = 4.0


def banner(tft, fonts, line1, line2):
    f1, f2 = fonts
    img = Image.new("RGB", (tft.width, tft.height), (20, 70, 40))
    d = ImageDraw.Draw(img)
    d.rectangle([4, 4, tft.width - 5, tft.height - 5], outline=(255, 255, 255), width=4)
    for i in range(0, tft.width, 40):
        d.line([(i, 0), (i, tft.height)], fill=(35, 110, 65))
    tw = d.textlength(line1, font=f1)
    d.text(((tft.width - tw) / 2, 95), line1, font=f1, fill=(255, 255, 255))
    tw = d.textlength(line2, font=f2)
    d.text(((tft.width - tw) / 2, 180), line2, font=f2, fill=(255, 235, 150))
    tft.blit(img)


def main():
    require_exclusive((C.TFT_PIN_DC, C.TFT_PIN_RST,
                       C.ADS_PIN_DRDY, C.ADS_PIN_START, C.ADS_PIN_RESET),
                      "จอและ ADC")

    print("=" * 66)
    print("วาดภาพครั้งเดียว แล้วไม่วาดซ้ำอีกเลย")
    print("ภาพหายตอนขั้นไหน = ขั้นนั้นคือต้นเหตุ")
    print("=" * 66)

    tft = ST7796(bus=C.TFT_BUS, dev=C.TFT_DEV, speed_hz=C.TFT_SPI_HZ,
                 pin_dc=C.TFT_PIN_DC, pin_rst=C.TFT_PIN_RST,
                 rotation=C.TFT_ROTATION, invert=C.TFT_INVERT, bgr=C.TFT_BGR)
    fonts = (load_font(44), load_font(24))

    try:
        banner(tft, fonts, "ภาพทดสอบ", "ภาพนี้ต้องอยู่จนจบ")
        print("\n[0] วาดภาพแล้ว — ควรเห็นพื้นเขียวมีกรอบขาว")
        time.sleep(PAUSE)

        # ---------------------------------------------- ขั้น A
        print("\n[A] เปิด /dev/spidev0.0 เฉย ๆ ยังไม่รับส่งอะไร")
        s = spidev.SpiDev()
        s.open(C.ADS_BUS, C.ADS_DEV)
        s.mode = 1
        s.max_speed_hz = C.ADS_SPI_HZ
        print("    เปิดแล้ว — ดูจอ")
        time.sleep(PAUSE)

        # ---------------------------------------------- ขั้น B
        print("\n[B] รับส่งข้อมูลบนบัส SPI0 จำนวน 300 ครั้ง (ไม่แตะขา GPIO เลย)")
        for _ in range(300):
            s.xfer2([0x20, 0x00, 0x00, 0x00])
        print("    ส่งครบแล้ว — ดูจอ")
        time.sleep(PAUSE)

        # ---------------------------------------------- ขั้น C
        print("\n[C] ส่งข้อมูลก้อนใหญ่บน SPI0 (เลียนแบบการอ่านต่อเนื่อง)")
        for _ in range(60):
            s.xfer2([0x12] + [0x00] * 6)
        s.close()
        print("    ปิดบัสแล้ว — ดูจอ")
        time.sleep(PAUSE)

        print("\n" + "=" * 66)
        print("ภาพหายตอนไหน")
        print()
        print("  ไม่หายเลย   -> บัส SPI0 ไม่ได้กวนจอ ปัญหาอยู่ที่อื่น")
        print("  หายตอน A   -> แค่เปิดบัสก็กวนแล้ว = ขา SPI0 ถูกมุกซ์ทับขาของจอ")
        print("  หายตอน B   -> การรับส่งบน SPI0 ไปโดนสายของจอ")
        print("  หายตอน C   -> เหมือน B")
        print()
        print("ถ้าหายตอน B หรือ C แปลว่ามีสายของบอร์ด ADC เสียบโดนขาบัส SPI1")
        print("ให้ไล่สายสามเส้นนี้เป็นอันดับแรก")
        print("   ADC SCLK ต้องอยู่ Pin 23  (ห้ามไปอยู่ Pin 40)")
        print("   ADC DIN  ต้องอยู่ Pin 19  (ห้ามไปอยู่ Pin 38)")
        print("   ADC DOUT ต้องอยู่ Pin 21  (ห้ามไปอยู่ Pin 35)")
        print("=" * 66)
    finally:
        try:
            tft.close()
        except Exception:
            pass
        try:
            from gpiozero import Device
            if Device.pin_factory is not None:
                Device.pin_factory.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
