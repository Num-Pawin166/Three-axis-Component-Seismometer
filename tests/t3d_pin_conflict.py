#!/usr/bin/env python3
"""
t3d_pin_conflict.py — หาว่าขาของ ADC ไปชนกับจอหรือเปล่า

ใช้เมื่อ: จอขึ้นภาพได้ตอนอยู่เฉย ๆ แต่ขาวทันทีที่เธรด ADC เริ่มทำงาน
ถ้าสายเสียบผิดขา การกระตุก RESET ของ ADC จะไปรีเซ็ตจอแทน

วิธีทำงาน: วาดภาพขึ้นจอ แล้วกระตุกขาของ ADC ทีละขา
หลังกระตุกแต่ละครั้งจะหยุดให้ดูจอ 3 วินาที ถ้าจอขาวตอนไหน ขานั้นคือตัวปัญหา

จอจะ **ไม่ถูกวาดซ้ำ** ระหว่างทดสอบ เพื่อให้เห็นชัดว่าภาพหายเพราะอะไร

รัน:  python3 tests/t3d_pin_conflict.py
"""
import _path  # noqa
from _guard import require_exclusive
import time

from PIL import Image, ImageDraw
from gpiozero import DigitalOutputDevice

import config as C
from drivers.st7796 import ST7796, load_font

PAUSE = 3.0


def banner(tft, fonts, line1, line2):
    f1, f2 = fonts
    img = Image.new("RGB", (tft.width, tft.height), (20, 60, 110))
    d = ImageDraw.Draw(img)
    d.rectangle([4, 4, tft.width - 5, tft.height - 5], outline=(255, 255, 255), width=4)
    for i in range(0, tft.width, 40):
        d.line([(i, 0), (i, tft.height)], fill=(40, 90, 150))
    tw = d.textlength(line1, font=f1)
    d.text(((tft.width - tw) / 2, 90), line1, font=f1, fill=(255, 255, 255))
    tw = d.textlength(line2, font=f2)
    d.text(((tft.width - tw) / 2, 180), line2, font=f2, fill=(255, 235, 150))
    tft.blit(img)


def main():
    require_exclusive((C.TFT_PIN_DC, C.TFT_PIN_RST,
                       C.ADS_PIN_DRDY, C.ADS_PIN_START, C.ADS_PIN_RESET),
                      "จอและ ADC")

    print("=" * 66)
    print("จะวาดภาพขึ้นจอหนึ่งครั้ง แล้วกระตุกขาของ ADC ทีละขา")
    print("ภาพจะไม่ถูกวาดซ้ำอีกเลย ดังนั้นถ้าภาพหายไป แปลว่าขานั้นไปโดนจอ")
    print("=" * 66)

    tft = ST7796(bus=C.TFT_BUS, dev=C.TFT_DEV, speed_hz=C.TFT_SPI_HZ,
                 pin_dc=C.TFT_PIN_DC, pin_rst=C.TFT_PIN_RST,
                 rotation=C.TFT_ROTATION, invert=C.TFT_INVERT, bgr=C.TFT_BGR)
    fonts = (load_font(44), load_font(24))

    try:
        banner(tft, fonts, "ภาพทดสอบ", "ภาพนี้ต้องอยู่จนจบ")
        print("\n[0] วาดภาพแล้ว — ดูที่จอ ตอนนี้ควรเห็นภาพสีน้ำเงินมีกรอบขาว")
        print(f"    ถ้าตอนนี้ขาวอยู่แล้ว ให้หยุดเลย ปัญหาไม่ได้อยู่ที่ขา ADC")
        time.sleep(PAUSE)

        targets = [
            (C.ADS_PIN_RESET, "RESET ของ ADC", 32),
            (C.ADS_PIN_START, "START ของ ADC", 31),
        ]
        for pin, label, header_pin in targets:
            print(f"\n[{pin}] กำลังกระตุกขา GPIO {pin} ({label}, ควรอยู่ที่ Pin {header_pin})")
            o = DigitalOutputDevice(pin, initial_value=True)
            for _ in range(4):
                o.off(); time.sleep(0.05)
                o.on(); time.sleep(0.05)
            o.close()
            print(f"      กระตุกเสร็จ — ดูจอ 3 วินาที ภาพยังอยู่ไหม")
            time.sleep(PAUSE)

        # ขา DRDY เป็นขาเข้า แค่จองดูว่าชนอะไรไหม
        print(f"\n[{C.ADS_PIN_DRDY}] จองขา GPIO {C.ADS_PIN_DRDY} (DRDY, ควรอยู่ที่ Pin 7) เป็นขาเข้า")
        from gpiozero import DigitalInputDevice
        d_in = DigitalInputDevice(C.ADS_PIN_DRDY)
        lv = [d_in.value for _ in range(50)]
        d_in.close()
        print(f"      อ่านได้ 1 จำนวน {sum(lv)}/50 ครั้ง")
        time.sleep(1.0)

        print("\n" + "=" * 66)
        print("ตอบคำถามเดียว: ภาพบนจอหายตอนไหน")
        print()
        print("  ไม่หายเลย        -> ขา ADC ไม่ได้ชนกับจอ ต้องหาสาเหตุอื่น")
        print(f"  หายตอนกระตุก GPIO {C.ADS_PIN_RESET} -> สาย RESET ของ ADC เสียบผิดไปโดนจอ")
        print(f"  หายตอนกระตุก GPIO {C.ADS_PIN_START} -> สาย START ของ ADC เสียบผิดไปโดนจอ")
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
