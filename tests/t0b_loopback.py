#!/usr/bin/env python3
"""
t0b_loopback.py — พิสูจน์ว่าสาย DIN กับ DOUT ช็อตถึงกันหรือเปล่า

หลักการ: ส่งเลขสุ่ม ๆ ที่ไม่ใช่คำสั่งของชิปออกไป
  - ถ้าสายปกติ ชิปจะไม่ตอบอะไรที่เหมือนกับที่เราส่ง
  - ถ้าสาย DIN กับ DOUT แตะกัน สิ่งที่ส่งออกไปจะวิ่งกลับมาเหมือนเดิมเป๊ะทุกไบต์

รัน:  python3 tests/t0b_loopback.py
"""
import _path  # noqa
from _guard import require_exclusive

import spidev

import config as C

PATTERNS = [            # ไบต์แรกต้อง >= 0x60 เพื่อไม่ให้ตรงกับคำสั่งจริงของชิป
    [0xA5, 0x5A, 0x3C, 0xC3],
    [0xFF, 0x00, 0xFF, 0x00],
    [0x7E, 0x81, 0x24, 0x99],
    [0xDE, 0xAD, 0xBE, 0xEF],
    [0x00, 0x00, 0x00, 0x00],
]
BAR = "-" * 66


def main():
    require_exclusive((C.ADS_PIN_DRDY, C.ADS_PIN_START, C.ADS_PIN_RESET), "ชิป ADC")

    s = spidev.SpiDev()
    s.open(C.ADS_BUS, C.ADS_DEV)
    s.mode = 1
    s.max_speed_hz = 500_000

    print(f"{BAR}\nส่งเลขที่ไม่ใช่คำสั่งของชิป แล้วดูว่าได้อะไรกลับมา\n{BAR}")
    echo = zero = other = 0
    try:
        for p in PATTERNS:
            r = s.xfer2(list(p))
            tx = " ".join(f"{b:02X}" for b in p)
            rx = " ".join(f"{b:02X}" for b in r)
            if r == p and any(p):
                tag = "<<< สะท้อนกลับเหมือนเดิมเป๊ะ"
                echo += 1
            elif not any(r):
                tag = "(ไม่มีอะไรกลับมา)"
                zero += 1
            else:
                tag = ""
                other += 1
            print(f"   ส่ง {tx}   ได้ {rx}   {tag}")
    finally:
        s.close()

    print(f"\n{BAR}\nสรุป\n{BAR}")
    live = [p for p in PATTERNS if any(p)]
    if echo == len(live):
        print("  ทุกลายได้กลับมาเหมือนเดิมเป๊ะ")
        print("  -> สาย DIN กับ DOUT ช็อตถึงกันแน่นอน ชิปไม่ได้มีส่วนร่วมเลย")
        print()
        print("  ไปดูสามจุดนี้")
        print("    1. ปลายสายสองเส้นที่หัวต่อบนบอร์ด ADS1263 แตะกันไหม")
        print("    2. ใต้กาวร้อนมีตะกั่วหรือลวดเกยกันหรือเปล่า")
        print("    3. ฝั่ง Pi เสียบคาบสองเข็มพร้อมกันไหม (Pin 19 กับ Pin 21 อยู่ติดกัน)")
    elif echo:
        print(f"  สะท้อนกลับ {echo} ลาย จาก {len(live)} ลาย")
        print("  -> สายน่าจะแตะกันแบบไม่สนิท ขยับแล้วติด ๆ ดับ ๆ")
    elif zero == len(PATTERNS):
        print("  ไม่มีอะไรกลับมาเลย -> สาย DOUT ไม่ได้ต่อถึง Pi หรือชิปไม่ทำงาน")
    else:
        print("  ได้ค่าที่ไม่ใช่ทั้งการสะท้อนและไม่ใช่ศูนย์")
        print("  -> มีสัญญาณจริงบนสาย ลองรัน t2_ads1263.py อีกรอบ")


if __name__ == "__main__":
    main()
