#!/usr/bin/env python3
"""
splash_boot.py — ขึ้นโลโก้ให้เร็วที่สุดเท่าที่ทำได้ตอนบูต

ต่างจาก splash.py ตรงที่ตัวนี้ "ไม่คิดอะไรเลย" แค่เทไฟล์ภาพดิบขึ้นจอ
    - ไม่ import numpy และไม่ import PIL  (สองตัวนี้กินเวลาเกือบวินาทีบน Pi)
    - ไม่ต้องย่อรูป ไม่ต้องวาดตัวหนังสือ ไม่ต้องแปลงสี
    - อ่านไฟล์ splash.raw ที่เตรียมไว้ล่วงหน้าแล้วส่งเข้า SPI ตรง ๆ

สร้างไฟล์ภาพดิบก่อนหนึ่งครั้งด้วย
    python3 splash.py --bake

ข้อจำกัดที่แก้ไม่ได้ด้วยซอฟต์แวร์
    จอ SPI ไม่มีภาพของตัวเอง ต้องมีคนส่งภาพไปให้เท่านั้น
    และจะส่งได้ก็ต่อเมื่อเคอร์เนลเปิดบัส SPI แล้ว
    เพราะฉะนั้นเร็วที่สุดคือ "ทันทีที่ /dev/spidev โผล่" ไม่ใช่ทันทีที่กดปุ่มเปิด
"""
import os
import sys
import time

T_START = time.monotonic()
try:        # เวลาที่เครื่องเปิดมาแล้ว ใช้ดูว่าเราเริ่มช้าหรือเร็วเทียบกับการบูต
    with open("/proc/uptime") as _f:
        BOOT0 = T_START - float(_f.read().split()[0])
except Exception:
    BOOT0 = None

# gpiozero จะไล่ทดสอบวิธีคุมขาทีละแบบถ้าไม่บอกไว้ ซึ่งกินเวลาเกือบวินาทีบน Pi
# บอกตรง ๆ ว่าใช้ lgpio จะข้ามขั้นตอนไล่หาไปได้เลย
os.environ.setdefault("GPIOZERO_PIN_FACTORY", "lgpio")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import config as C          # noqa: E402  (ไฟล์เล็ก ไม่มี dependency หนัก)

RAW = os.path.join(HERE, "splash.raw")
WAIT_DEV = 25.0             # รอ /dev/spidev นานสุดกี่วินาที

# ---- คำสั่งของ ST7796S เท่าที่จำเป็น ----
SWRESET, SLPOUT, NORON = 0x01, 0x11, 0x13
INVOFF, INVON, DISPON = 0x20, 0x21, 0x29
CASET, RASET, RAMWR = 0x2A, 0x2B, 0x2C
MADCTL, COLMOD, CSCON = 0x36, 0x3A, 0xF0
MAD_MY, MAD_MX, MAD_MV, MAD_BGR = 0x80, 0x40, 0x20, 0x08


def madctl(rotation, bgr):
    base = MAD_BGR if bgr else 0
    return {0: MAD_MX | base,
            90: MAD_MV | base,
            180: MAD_MY | base,
            270: MAD_MV | MAD_MX | MAD_MY | base}[rotation % 360]


def main():
    if not os.path.exists(RAW):
        print(f"ไม่พบ {RAW} — สร้างก่อนด้วย  python3 splash.py --bake", flush=True)
        return 1

    # เวลาตั้งแต่เครื่องเริ่มบูตจนตัวแปลภาษาเริ่มทำงาน
    # ถ้าค่าดูไม่สมเหตุสมผล (เช่นรันเองทีหลัง) ไม่ต้องแสดง
    since_boot = (T_START - BOOT0) if BOOT0 else 0.0
    lap = {}
    if 0.0 < since_boot < 120.0:
        lap["ตั้งแต่เปิดเครื่อง"] = since_boot
    t0 = time.monotonic()
    dev = f"/dev/spidev{C.TFT_BUS}.{C.TFT_DEV}"
    while not os.path.exists(dev) and time.monotonic() - t0 < WAIT_DEV:
        time.sleep(0.05)                      # เช็คถี่ ๆ จะได้เริ่มทันทีที่พร้อม
    lap["รอ /dev/spidev"] = time.monotonic() - t0
    if not os.path.exists(dev):
        print(f"ไม่พบ {dev} ภายใน {WAIT_DEV:g} วินาที", flush=True)
        return 1

    t = time.monotonic()
    import spidev
    from gpiozero import DigitalOutputDevice
    lap["โหลด spidev/gpiozero"] = time.monotonic() - t

    t = time.monotonic()
    with open(RAW, "rb") as f:
        buf = f.read()
    lap["อ่านไฟล์ภาพ"] = time.monotonic() - t

    rot = C.TFT_ROTATION % 360
    W, H = (480, 320) if rot in (90, 270) else (320, 480)
    if len(buf) != W * H * 2:
        print(f"ขนาดไฟล์ภาพไม่ตรงกับจอ ({len(buf)} ไบต์ ควรเป็น {W*H*2})",
              flush=True)
        print("สร้างใหม่ด้วย  python3 splash.py --bake", flush=True)
        return 1

    spi = dc = rst = bl = None
    try:
        spi = spidev.SpiDev()
        spi.open(C.TFT_BUS, C.TFT_DEV)
        spi.mode = 0
        spi.max_speed_hz = C.TFT_SPI_HZ

        t_panel = time.monotonic()
        dc = DigitalOutputDevice(C.TFT_PIN_DC, initial_value=True)
        rst = (DigitalOutputDevice(C.TFT_PIN_RST, initial_value=True)
               if C.TFT_PIN_RST else None)
        pin_bl = getattr(C, "TFT_PIN_BL", None)
        # เปิดขาไฟส่องหลังไว้ที่ "ดับ" ก่อน แล้วค่อยเปิดตอนภาพขึ้นครบ
        bl = (DigitalOutputDevice(pin_bl, initial_value=False)
              if pin_bl is not None else None)

        def cmd(c, *args):
            dc.off()
            spi.writebytes([c & 0xFF])
            if args:
                dc.on()
                spi.writebytes(list(args))

        if rst is not None:
            rst.on(); time.sleep(0.02)
            rst.off(); time.sleep(0.05)
            rst.on(); time.sleep(0.12)

        cmd(SWRESET); time.sleep(0.12)
        cmd(SLPOUT); time.sleep(0.12)
        cmd(CSCON, 0xC3)                      # ปลดล็อกชุดคำสั่งที่สอง
        cmd(CSCON, 0x96)
        cmd(MADCTL, madctl(rot, C.TFT_BGR))
        cmd(COLMOD, 0x55)                     # 16 บิตต่อพิกเซล
        cmd(0xB4, 0x01)
        cmd(0xB6, 0x80, 0x02, 0x3B)
        cmd(0xE8, 0x40, 0x8A, 0x00, 0x00, 0x29, 0x19, 0xA5, 0x33)
        cmd(0xC1, 0x06)
        cmd(0xC2, 0xA7)
        cmd(0xC5, 0x18); time.sleep(0.12)
        cmd(0xE0, 0xF0, 0x09, 0x0B, 0x06, 0x04, 0x15, 0x2F,
            0x54, 0x42, 0x3C, 0x17, 0x14, 0x18, 0x1B)
        cmd(0xE1, 0xF0, 0x09, 0x0B, 0x06, 0x04, 0x03, 0x2D,
            0x43, 0x42, 0x3B, 0x16, 0x14, 0x17, 0x1B)
        time.sleep(0.12)
        cmd(CSCON, 0x3C)                      # ล็อกกลับ
        cmd(CSCON, 0x69); time.sleep(0.12)
        cmd(INVON if C.TFT_INVERT else INVOFF)
        cmd(NORON); time.sleep(0.02)
        cmd(DISPON); time.sleep(0.12)
        lap["ตั้งค่าพาเนล"] = time.monotonic() - t_panel

        t = time.monotonic()
        cmd(CASET, 0, 0, (W - 1) >> 8, (W - 1) & 0xFF)
        cmd(RASET, 0, 0, (H - 1) >> 8, (H - 1) & 0xFF)
        cmd(RAMWR)
        dc.on()
        mv = memoryview(buf)
        step = 60000                          # เผื่อเครื่องที่ยังไม่ขยาย spidev.bufsiz
        for i in range(0, len(mv), step):
            spi.writebytes2(mv[i:i + step])

        lap["ส่งภาพขึ้นจอ"] = time.monotonic() - t
        if bl is not None:
            bl.on()                           # ภาพครบแล้วค่อยเปิดไฟ
        total = time.monotonic() - T_START
        print(f"ขึ้นโลโก้แล้ว รวม {total:.2f} วินาที", flush=True)
        for k, v in lap.items():
            if v > 0.0005:
                print(f"   {k:<22s} {v*1000:7.0f} ms", flush=True)
        return 0
    except Exception as e:
        print(f"ขึ้นโลโก้ไม่ได้: {e}", flush=True)
        return 1
    finally:
        try:
            if spi is not None:
                spi.close()
        except Exception:
            pass
        for obj in (dc, rst, bl):
            if obj is not None:
                try:
                    obj.close()
                except Exception:
                    pass
        # คืนขาแล้ว gpiozero จะตั้งขาเป็นขาอ่าน ไฟอาจดับตาม
        # จึงตรึงไว้เป็นขาออกระดับสูง ภาพจะค้างจนแอปหลักมารับช่วง
        pin_bl = getattr(C, "TFT_PIN_BL", None)
        if pin_bl is not None:
            os.system(f"pinctrl set {int(pin_bl)} op dh >/dev/null 2>&1")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)