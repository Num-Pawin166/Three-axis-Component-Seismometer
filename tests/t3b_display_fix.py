#!/usr/bin/env python3
"""
t3b_display_fix.py — ไล่หาลำดับตั้งค่าจอที่ใช้ได้กับพาเนลตัวนี้

ใช้เมื่อจอติดไฟ backlight แต่ขาวโพลน ไม่ขึ้นภาพ
อาการนั้นแปลว่าพาเนลไม่เคยถูกตั้งค่าให้พร้อมรับข้อมูลภาพ
ST7796S มีหลายล็อตที่ต้องการลำดับคำสั่งไม่เหมือนกัน

สคริปต์จะลองทีละสูตร แต่ละสูตรเติมสีพื้นแล้วเขียนเลขตัวใหญ่ ๆ ค้างไว้ 4 วินาที
ดูที่จอแล้วจำว่า "เลขอะไรขึ้น" จากนั้นบอกผมว่าสูตรไหนใช้ได้

รัน:  python3 tests/t3b_display_fix.py
      python3 tests/t3b_display_fix.py 3        ลองเฉพาะสูตรที่ 3 แล้วค้างไว้
"""
import _path  # noqa
from _guard import require_exclusive
import sys
import time

import spidev
from gpiozero import DigitalOutputDevice
from PIL import Image, ImageDraw

import config as C
from drivers.st7796 import load_font

W, H = 480, 320
HOLD = 4.0
COLORS = [(200, 30, 30), (30, 170, 70), (40, 90, 220), (200, 140, 20),
          (150, 40, 180), (20, 160, 170)]


class Raw:
    """คุมจอระดับดิบ ไม่ผ่านไดรเวอร์ เพื่อลองลำดับคำสั่งได้อิสระ"""

    def __init__(self, hz):
        self.spi = spidev.SpiDev()
        self.spi.open(C.TFT_BUS, C.TFT_DEV)
        self.spi.mode = 0
        self.spi.max_speed_hz = hz
        self.dc = DigitalOutputDevice(C.TFT_PIN_DC, initial_value=True)
        self.rst = DigitalOutputDevice(C.TFT_PIN_RST, initial_value=True)

    def cmd(self, c, *a):
        self.dc.off()
        self.spi.writebytes([c])
        if a:
            self.dc.on()
            self.spi.writebytes(list(a))

    def reset(self):
        self.rst.on(); time.sleep(0.02)
        self.rst.off(); time.sleep(0.05)
        self.rst.on(); time.sleep(0.15)

    def show(self, img, madctl):
        self.cmd(0x2A, 0, 0, (W - 1) >> 8, (W - 1) & 0xFF)
        self.cmd(0x2B, 0, 0, (H - 1) >> 8, (H - 1) & 0xFF)
        self.cmd(0x2C)
        import numpy as np
        a = np.asarray(img.convert("RGB"), dtype=np.uint16)
        v = ((a[:, :, 0] & 0xF8) << 8) | ((a[:, :, 1] & 0xFC) << 3) | (a[:, :, 2] >> 3)
        buf = v.astype(">u2").tobytes()
        self.dc.on()
        mv = memoryview(buf)
        for i in range(0, len(mv), 60000):
            self.spi.writebytes2(mv[i:i + 60000])

    def close(self):
        for o in (self.dc, self.rst):
            try:
                o.close()
            except Exception:
                pass
        try:
            self.spi.close()
        except Exception:
            pass


# ---------------------------------------------------------------- สูตรต่าง ๆ
def init_minimal(d, madctl, inv):
    d.cmd(0x01); time.sleep(0.12)
    d.cmd(0x11); time.sleep(0.12)
    d.cmd(0x3A, 0x55)
    d.cmd(0x36, madctl)
    d.cmd(0x21 if inv else 0x20)
    d.cmd(0x29); time.sleep(0.05)


def init_full(d, madctl, inv):
    d.cmd(0x01); time.sleep(0.12)
    d.cmd(0x11); time.sleep(0.12)
    d.cmd(0xF0, 0xC3)
    d.cmd(0xF0, 0x96)
    d.cmd(0x36, madctl)
    d.cmd(0x3A, 0x55)
    d.cmd(0xB4, 0x01)
    d.cmd(0xB6, 0x80, 0x02, 0x3B)
    d.cmd(0xE8, 0x40, 0x8A, 0x00, 0x00, 0x29, 0x19, 0xA5, 0x33)
    d.cmd(0xC1, 0x06)
    d.cmd(0xC2, 0xA7)
    d.cmd(0xC5, 0x18); time.sleep(0.12)
    d.cmd(0xE0, 0xF0, 0x09, 0x0B, 0x06, 0x04, 0x15, 0x2F,
          0x54, 0x42, 0x3C, 0x17, 0x14, 0x18, 0x1B)
    d.cmd(0xE1, 0xF0, 0x09, 0x0B, 0x06, 0x04, 0x03, 0x2D,
          0x43, 0x42, 0x3B, 0x16, 0x14, 0x17, 0x1B)
    time.sleep(0.12)
    d.cmd(0xF0, 0x3C)
    d.cmd(0xF0, 0x69); time.sleep(0.12)
    d.cmd(0x21 if inv else 0x20)
    d.cmd(0x13); time.sleep(0.02)
    d.cmd(0x29); time.sleep(0.12)


def init_alt(d, madctl, inv):
    """อีกสูตรที่พบบ่อยในโมดูลจีน ใช้ค่าจ่ายไฟต่างออกไป"""
    d.cmd(0x01); time.sleep(0.12)
    d.cmd(0x11); time.sleep(0.12)
    d.cmd(0xF0, 0xC3)
    d.cmd(0xF0, 0x96)
    d.cmd(0x36, madctl)
    d.cmd(0x3A, 0x55)
    d.cmd(0xB0, 0x80)
    d.cmd(0xB6, 0x00, 0x02)
    d.cmd(0xB5, 0x02, 0x03, 0x00, 0x04)
    d.cmd(0xB1, 0x80, 0x10)
    d.cmd(0xB4, 0x00)
    d.cmd(0xC5, 0x24)
    d.cmd(0xC6, 0x0F)
    d.cmd(0xE4, 0x31)
    d.cmd(0xE8, 0x40, 0x8A, 0x00, 0x00, 0x29, 0x19, 0xA5, 0x33)
    d.cmd(0xC2)
    d.cmd(0xA7)
    d.cmd(0xE0, 0xF0, 0x09, 0x13, 0x12, 0x12, 0x2B, 0x3C,
          0x44, 0x4B, 0x1B, 0x18, 0x17, 0x1D, 0x21)
    d.cmd(0xE1, 0xF0, 0x09, 0x13, 0x0C, 0x0D, 0x27, 0x3B,
          0x44, 0x4D, 0x0B, 0x17, 0x17, 0x1D, 0x21)
    time.sleep(0.12)
    d.cmd(0xF0, 0x3C)
    d.cmd(0xF0, 0x69); time.sleep(0.12)
    d.cmd(0x21 if inv else 0x20)
    d.cmd(0x29); time.sleep(0.12)


VARIANTS = [
    ("เต็มสูตร ST7796S  40 MHz  INVOFF", init_full, 0xE8, False, 40_000_000),
    ("เต็มสูตร ST7796S  16 MHz  INVOFF", init_full, 0xE8, False, 16_000_000),
    ("เต็มสูตร ST7796S  16 MHz  INVON ", init_full, 0xE8, True, 16_000_000),
    ("สูตรทางเลือก      16 MHz  INVOFF", init_alt, 0xE8, False, 16_000_000),
    ("สูตรสั้น (ของเดิม) 16 MHz  INVOFF", init_minimal, 0xE8, False, 16_000_000),
    ("เต็มสูตร  MADCTL 0x28 แทน 0xE8  ", init_full, 0x28, False, 16_000_000),
]


def run_variant(i):
    name, fn, madctl, inv, hz = VARIANTS[i]
    col = COLORS[i % len(COLORS)]
    print(f"\n[{i+1}] {name}")
    d = Raw(hz)
    try:
        d.reset()
        fn(d, madctl, inv)
        img = Image.new("RGB", (W, H), col)
        dr = ImageDraw.Draw(img)
        f1, f2 = load_font(150), load_font(22)
        s = str(i + 1)
        tw = dr.textlength(s, font=f1)
        dr.text(((W - tw) / 2, 40), s, font=f1, fill=(255, 255, 255))
        dr.text((16, 16), name.strip(), font=f2, fill=(255, 255, 255))
        dr.rectangle([4, 4, W - 5, H - 5], outline=(255, 255, 255), width=3)
        d.show(img, madctl)
        print(f"    ส่งภาพแล้ว — ดูที่จอ ถ้าขึ้นเลข {i+1} บนพื้นสี แปลว่าสูตรนี้ใช้ได้")
    finally:
        time.sleep(HOLD)
        d.close()          # ปิดเฉพาะขา ไม่ปิด factory ไม่งั้นสูตรถัดไปจองขาไม่ได้


def main():
    require_exclusive((C.TFT_PIN_DC, C.TFT_PIN_RST), "จอแสดงผล")
    args = sys.argv[1:]
    if args:
        i = int(args[0]) - 1
        if not 0 <= i < len(VARIANTS):
            print(f"มีสูตรที่ 1 ถึง {len(VARIANTS)} เท่านั้น")
            return
        run_variant(i)
        return

    print("=" * 66)
    print("จะลองทีละสูตร สูตรละ 4 วินาที — มองที่จอตลอดเวลา")
    print("จำให้ได้ว่า 'เลขอะไรขึ้นบนจอ' แล้วบอกเลขนั้นกลับมา")
    print("ถ้าขาวตลอดทุกสูตร แปลว่าปัญหาอยู่ที่สายหรือพาเนล ไม่ใช่ลำดับคำสั่ง")
    print("=" * 66)
    for i in range(len(VARIANTS)):
        run_variant(i)
    print("\n" + "=" * 66)
    print("จบแล้ว — เลขสุดท้ายที่เห็นขึ้นบนจอคือสูตรที่ใช้ได้")
    print("บอกเลขนั้นมา เดี๋ยวผมแก้ st7796.py ให้ใช้สูตรนั้นถาวร")
    print("=" * 66)


if __name__ == "__main__":
    main()
