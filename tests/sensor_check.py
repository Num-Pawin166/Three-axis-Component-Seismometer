#!/usr/bin/env python3
"""
sensor_check.py — ตรวจว่าเซ็นเซอร์แต่ละแกนต่ออยู่จริงและตอบสนองแรงสั่นจริง

  [1] ขา input มีทางเดินไฟ DC หรือยัง (bias)
  [2] เซ็นเซอร์ต่อถึงกันไหม — วัดผลต่างตรง ๆ ไม่ฉีดกระแส
  [3] ความต้านทานขดลวด (ทำได้ต่อเมื่อต่อ bias แล้ว)
  [4] อ่านสัญญาณจริง แล้วเคาะโต๊ะดูการตอบสนอง

เกณฑ์ข้อ [2] มาจากการวัดจริง: คู่ที่มีขดลวดเชื่อมอยู่จะให้ค่ากลางราว +0.48 mV
และวัดซ้ำได้ค่าเดิมในระดับ 0.01 mV ส่วนคู่ที่ลอยจะได้หลายสิบ mV และเปลี่ยนทุกครั้ง

รัน:  python3 tests/sensor_check.py
"""
import _path  # noqa
from _guard import require_exclusive
import statistics
import subprocess
import sys
import time

import config as C
from drivers.ads1263 import ADS1263, ADS1263Error, MUX_AINCOM

BAR = "=" * 66
PAIRS = [(name, p, q) for name, (p, q) in C.CHANNELS.items()]
CONTROL = [("ควบคุม 6-7", 6, 7), ("ควบคุม 8-9", 8, 9)]   # คู่ที่รู้ว่าไม่ได้ต่ออะไร


def head(n, t):
    print(f"\n{BAR}\n[{n}] {t}\n{BAR}")


def main():
    require_exclusive((C.ADS_PIN_DRDY, C.ADS_PIN_START, C.ADS_PIN_RESET),
                      "ชิป ADC")
    adc = ADS1263(bus=C.ADS_BUS, dev=C.ADS_DEV, speed_hz=C.ADS_SPI_HZ,
                  pin_reset=C.ADS_PIN_RESET, pin_start=C.ADS_PIN_START,
                  pin_drdy=C.ADS_PIN_DRDY, vref=C.ADS_VREF)
    try:
        adc.reset()
        name, rev, raw = adc.chip_id()
        print(f"ชิป: {name} rev {rev}  (ID = 0x{raw:02X})")
        if name not in ("ADS1263", "ADS1262"):
            print("!! ไม่เจอชิป — หยุดตรงนี้")
            return

        # ---------------------------------------------------------- [1]
        head(1, "ขา input มีทางเดินไฟ DC หรือยัง (bias)")
        adc.configure(gain=1, rate=400, filt="sinc4", one_shot=True)
        biased = True
        for ain in range(6):
            vals = [adc.convert(ain, MUX_AINCOM)[0] for _ in range(20)]
            dc = statistics.fmean(vals)
            sw = (max(vals) - min(vals)) * 1000.0
            floating = abs(dc) > 0.3 or sw > 50.0
            if floating:
                biased = False
            print(f"   AIN{ain} = {dc:7.3f} V   แกว่ง {sw:9.2f} mV   "
                  f"{'ยังลอย' if floating else 'มี bias'}")
        print("   -> " + ("ต่อ bias ครบแล้ว" if biased else
                          "ยังไม่ได้ต่อ bias (AIN1/3/5 -> AINCOM)"))

        # ---------------------------------------------------------- [2]
        head(2, "เซ็นเซอร์ต่อถึงกันไหม (วัดผลต่างตรง ไม่ฉีดกระแส)")
        conn = []
        for label, p, q in PAIRS + CONTROL:
            a = [adc.convert(p, q)[0] for _ in range(30)]
            b = [adc.convert(p, q)[0] for _ in range(30)]
            m1, m2 = statistics.fmean(a), statistics.fmean(b)
            sig = statistics.pstdev(a + b)
            linked = abs(m1) < 5e-3 and abs(m2) < 5e-3 and abs(m1 - m2) < 1e-3
            print(f"   {label:<12} AIN{p}-AIN{q}  = {m1*1000:+9.3f} mV   "
                  f"ซ้ำต่าง {abs(m1-m2)*1000:8.3f} mV   สัญญาณ {sig*1e6:9.1f} uV   "
                  f"{'ต่ออยู่' if linked else 'ไม่ต่อ'}")
            if linked and (label, p, q) in PAIRS:
                conn.append((label, p, q))
        print(f"   -> เจอเซ็นเซอร์ {len(conn)} ตัว: {[c[0] for c in conn]}")
        if not conn:
            print("   ไม่มีแกนไหนต่ออยู่เลย — ตรวจสายและจุดบัดกรีก่อน")
            return

        # ---------------------------------------------------------- [3]
        head(3, "ความต้านทานขดลวด")
        if not biased:
            print("   ข้ามการวัดความต้านทาน — ต้องต่อ bias ก่อน")
            print("   (ต่อ AIN1, AIN3, AIN5 เข้ากับ AINCOM แล้วรันใหม่)")
        else:
            from drivers.ads1263 import REG_IDACMUX, REG_IDACMAG
            for label, p, q in conn:
                adc.write_reg(REG_IDACMAG, 0x03)          # 50 uA
                adc.write_reg(REG_IDACMUX, (0x0F << 4) | p)
                time.sleep(0.05)
                v = statistics.fmean([adc.convert(p, q)[0] for _ in range(20)])
                adc.write_reg(REG_IDACMUX, 0xFF)
                adc.write_reg(REG_IDACMAG, 0x00)
                print(f"   {label}: {abs(v)/50e-6:8.1f} โอห์ม  "
                      f"(geophone 4.5 Hz ปกติราว 375 หรือ 1,800 โอห์ม)")

        # ---------------------------------------------------------- [4]
        head(4, f"อ่านสัญญาณจริงที่ gain {C.ADS_GAIN}")
        adc.configure(gain=C.ADS_GAIN, rate=C.ADS_RATE, filt=C.ADS_FILTER, one_shot=True)
        adc.self_offset_cal()

        print("   วางนิ่ง ๆ 3 วินาที...")
        base_dc, base_pk = {}, {}
        for label, p, q in conn:
            samples = [adc.convert(p, q)[0] for _ in range(150)]
            dc = statistics.fmean(samples)
            base_dc[label] = dc
            base_pk[label] = max(abs(v - dc) for v in samples)
            print(f"   {label}: DC {dc*1000:+8.3f} mV   นิ่ง {base_pk[label]*1e6:8.2f} uV "
                  f"= {base_pk[label]/C.GEO_SENS*1000:7.4f} mm/s")

        print("   ตอนนี้เคาะโต๊ะได้เลย — วัดพีค 6 วินาที")
        peak = {label: 0.0 for label, _, _ in conn}
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < 6.0:
            for label, p, q in conn:
                value = abs(adc.convert(p, q)[0] - base_dc[label])   # หักฐาน DC
                peak[label] = max(peak[label], value)

        for label, p, q in conn:
            ratio = peak[label] / max(base_pk[label], 1e-12)         # พีคเทียบพีค
            clipped = peak[label] > 0.95 * adc.fsr
            if clipped:
                verdict = "!! ชนขอบสเกล ค่าต่ำกว่าจริง — ลด ADS_GAIN ใน config.py"
            elif ratio > 5:
                verdict = "ตอบสนองดี"
            else:
                verdict = "แทบไม่ขยับ"
            print(f"   {label}: พีค {peak[label]*1000:8.3f} mV = "
                  f"{peak[label]/C.GEO_SENS*1000:8.3f} mm/s   "
                  f"แรงกว่าตอนนิ่ง {ratio:7.1f} เท่า  {verdict}")

        print("\n   หมายเหตุ: ตัวเลข 'เท่า' เทียบพีคกับพีคบนฐานเดียวกัน")
        print("   ถ้าได้เกิน 5 เท่าถือว่าตอบสนองจริง ถ้าได้ 1-2 เท่าคือแทบไม่ต่างจากน้อยส์")

    except ADS1263Error as e:
        print(f"\n!! ADS1263 error: {e}")
    finally:
        adc.close()
        try:
            from gpiozero import Device
            if Device.pin_factory is not None:
                Device.pin_factory.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
    sys.stdout.flush()
