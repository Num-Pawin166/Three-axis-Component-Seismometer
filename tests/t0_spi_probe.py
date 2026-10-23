#!/usr/bin/env python3
"""
t0_spi_probe.py — ตรวจว่าชิปบนบัส SPI ยังหายใจอยู่ไหม

ใช้เมื่อ t2 อ่านรีจิสเตอร์ได้ 0x00 ทั้งหมด ซึ่งแปลว่าไม่มีใครขับสาย MISO เลย
สคริปต์นี้ไม่ใช้ไดรเวอร์ ยิงไบต์ลงบัสตรง ๆ เพื่อแยกว่าเป็นปัญหา
ซอฟต์แวร์ (โหมด/ความเร็ว/เลือกผิดช่อง) หรือฮาร์ดแวร์ (ไฟ/สาย/คริสตัล)

รัน:  python3 tests/t0_spi_probe.py
"""
import _path  # noqa
from _guard import require_exclusive
import glob
import time

import spidev

import config as C

LINE = "-" * 66
CMD_RREG_ID = 0x20          # RREG | 0x00  (อ่านรีจิสเตอร์ ID)


def probe(bus, dev, mode, hz):
    """ยิงคำสั่งอ่าน ID หนึ่งครั้ง คืนไบต์ที่รับกลับมา"""
    s = spidev.SpiDev()
    try:
        s.open(bus, dev)
        s.mode = mode
        s.max_speed_hz = hz
        r1 = s.xfer2([CMD_RREG_ID, 0x00, 0x00, 0x00])
        r2 = s.xfer2([0xFF, 0xFF, 0xFF, 0xFF])      # ดันสาย MOSI เป็น 1 ทั้งหมด
        return r1, r2
    finally:
        try:
            s.close()
        except Exception:
            pass


def verdict(samples):
    flat = [b for r in samples for b in r]
    if all(b == 0x00 for b in flat):
        return "MISO ไม่ถูกขับเลย (ค้างที่ 0)"
    if all(b == 0xFF for b in flat):
        return "MISO ค้างที่ 1 (น่าจะไม่มีอะไรต่อ หรือ CS ไม่ทำงาน)"
    return "มีข้อมูลกลับมา"


def main():
    require_exclusive((C.ADS_PIN_DRDY, C.ADS_PIN_START, C.ADS_PIN_RESET), "บัส SPI และขา GPIO")
    print(f"{LINE}\nไฟล์อุปกรณ์ SPI ที่ระบบมี\n{LINE}")
    for d in sorted(glob.glob("/dev/spidev*")):
        print("  ", d)

    print(f"\n{LINE}\nยิงคำสั่งอ่านรีจิสเตอร์ ID ทุกโหมด/ความเร็ว\n{LINE}")
    print("  ค่าที่ถูกต้องคือไบต์ที่ 3 ต้องเป็น 0x03 (ADS1262) หรือ 0x23 (ADS1263)")
    print()
    found = False
    for bus, dev in sorted({(C.ADS_BUS, C.ADS_DEV), (0, 0), (0, 1)}):
        if not glob.glob(f"/dev/spidev{bus}.{dev}"):
            continue
        for mode in (1, 0, 2, 3):
            for hz in (2_000_000, 500_000, 100_000):
                try:
                    r1, r2 = probe(bus, dev, mode, hz)
                except Exception as e:
                    print(f"  spidev{bus}.{dev} mode{mode} {hz/1000:.0f}kHz -> เปิดไม่ได้: {e}")
                    continue
                hexed = " ".join(f"{b:02X}" for b in r1)
                note = ""
                if r1[2] in (0x03, 0x23) or r1[3] in (0x03, 0x23):
                    note = "   <<< เจอชิป!"
                    found = True
                print(f"  spidev{bus}.{dev} mode{mode} {hz/1000:6.0f}kHz -> {hexed}"
                      f"   {verdict([r1, r2])}{note}")
        print()

    print(f"{LINE}\nสถานะขาควบคุม\n{LINE}")
    try:
        from gpiozero import DigitalInputDevice, DigitalOutputDevice
        drdy = DigitalInputDevice(C.ADS_PIN_DRDY, pull_up=None, active_state=True)
        rst = DigitalOutputDevice(C.ADS_PIN_RESET, initial_value=True)
        start = DigitalOutputDevice(C.ADS_PIN_START, initial_value=False)

        lv = [drdy.value for _ in range(200)]
        print(f"  DRDY (GPIO {C.ADS_PIN_DRDY}) อ่าน 200 ครั้ง: "
              f"เป็น 1 จำนวน {sum(lv)} ครั้ง, เป็น 0 จำนวน {200-sum(lv)} ครั้ง")
        if sum(lv) == 200:
            print("     ค้างที่ 1 ตลอด — ชิปไม่เคยบอกว่าแปลงค่าเสร็จ")
        elif sum(lv) == 0:
            print("     ค้างที่ 0 ตลอด — สายอาจลัดลงกราวด์ หรือชิปไม่ได้ตั้งค่า")
        else:
            print("     มีการเปลี่ยนระดับ — ชิปน่าจะกำลังแปลงค่าอยู่")

        print("  ลองกระตุกขา RESET แล้วดูว่า DRDY ขยับไหม")
        rst.off(); time.sleep(0.05); rst.on(); time.sleep(0.2)
        lv2 = [drdy.value for _ in range(200)]
        print(f"     หลังรีเซ็ต: เป็น 1 จำนวน {sum(lv2)} ครั้ง")

        for o in (drdy, rst, start):
            o.close()
    except Exception as e:
        print("  ตรวจขา GPIO ไม่ได้:", e)

    print(f"\n{LINE}\nสรุป\n{LINE}")
    if found:
        print("  เจอชิปแล้ว — ดูว่าโหมด/ความเร็วไหนที่ใช้ได้ แล้วแก้ใน config.py")
    else:
        print("  ไม่เจอชิปในทุกโหมดและทุกความเร็ว")
        print("  แปลว่าเป็นเรื่องฮาร์ดแวร์ ไล่ตามนี้ตามลำดับ")
        print("    1. วัดไฟที่ขา VCC ของบอร์ด ADS1263 ต้องได้ 5 V และ GND ต้องถึงกันจริง")
        print("    2. ถอดแล้วเสียบสายใหม่ทีละเส้น โดยเฉพาะ DOUT(MISO) -> Pin 21 และ CS -> Pin 24")
        print("    3. เช็คว่าสายไม่ได้เลื่อนไปเข้าแถวขาคู่/ขาคี่สลับกัน")
        print("    4. ถ้าเพิ่งขยับบอร์ด ลองกดหัวต่อให้แน่นทุกจุด")
        print("    5. ถ้ายังไม่ได้ ลองสลับไปใช้สาย MISO เส้นอื่นเพื่อตัดเรื่องสายขาดใน")


if __name__ == "__main__":
    main()
