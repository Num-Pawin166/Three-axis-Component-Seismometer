#!/usr/bin/env python3
"""
t2_ads1263.py — ทดสอบ ADS1263 ทีละขั้น
  1) อ่าน chip ID           -> เช็คสาย SPI/ไฟเลี้ยง
  2) dump รีจิสเตอร์ทั้งหมด
  3) วัดไฟเลี้ยง AVDD/DVDD  -> เช็คว่าไฟถูกต้อง
  4) อ่านอุณหภูมิในชิป
  5) noise test (input ลัดวงจรภายใน) -> ดูว่า noise floor ต่ำแค่ไหน
  6) อ่าน 3 ช่องจริง + วัดอัตราการสแกน

รัน:  python3 tests/t2_ads1263.py
"""
import _path  # noqa
from _guard import require_exclusive
import statistics
import time

import config as C
from drivers.ads1263 import ADS1263, ADS1263Error, REG_NAMES, MUX_AINCOM

LINE = "-" * 62


def step(n, title):
    print(f"\n{LINE}\n[{n}] {title}\n{LINE}")


def main():
    require_exclusive((C.ADS_PIN_DRDY, C.ADS_PIN_START, C.ADS_PIN_RESET), "ชิป ADC")
    adc = ADS1263(bus=C.ADS_BUS, dev=C.ADS_DEV, speed_hz=C.ADS_SPI_HZ,
                  pin_reset=C.ADS_PIN_RESET, pin_start=C.ADS_PIN_START,
                  pin_drdy=C.ADS_PIN_DRDY, vref=C.ADS_VREF)
    try:
        step(1, "รีเซ็ตและอ่าน Chip ID")
        adc.reset()
        name, rev, raw = adc.chip_id()
        print(f"  ID register = 0x{raw:02X}  ->  {name}, revision {rev}")
        if name not in ("ADS1263", "ADS1262"):
            print("  !! ไม่เจอ ADS1263 — ตรวจสาย MISO/MOSI/SCLK/CS, ไฟเลี้ยง, "
                  "และว่าโมดูลมีคริสตัลทำงานหรือไม่")
            return

        step(2, "ตั้งค่าและ dump รีจิสเตอร์")
        adc.configure(gain=C.ADS_GAIN, rate=C.ADS_RATE, filt=C.ADS_FILTER, one_shot=True)
        regs = adc.read_regs(0x00, 0x1B)
        for i, v in enumerate(regs):
            print(f"  0x{i:02X} {REG_NAMES.get(i, ''):<10} = 0x{v:02X}  {v:08b}")

        step(3, "วัดไฟเลี้ยง")
        avdd = adc.read_supply("AVDD")
        dvdd = adc.read_supply("DVDD")
        print(f"  AVDD = {avdd:6.3f} V   (ควรใกล้ 5.0 V ถ้าจ่ายจาก Pin 2/4)")
        print(f"  DVDD = {dvdd:6.3f} V   (ควรใกล้ 3.3 V — ถ้าได้ 5 V แปลว่า IO เป็น 5 V "
              "ห้ามต่อ Pi ตรง!)")
        if dvdd > 3.8:
            print("  !! อันตราย: DVDD สูงเกิน 3.3 V — ตัดไฟแล้วตรวจจัมเปอร์บนบอร์ดก่อนใช้ต่อ")

        step(4, "อุณหภูมิภายในชิป")
        print(f"  T = {adc.read_temperature():.2f} °C")

        step(5, f"Noise floor (input ลัดวงจรที่ AINCOM, gain = {C.ADS_GAIN})")
        adc.configure(gain=C.ADS_GAIN, rate=C.ADS_RATE, filt=C.ADS_FILTER, one_shot=True)
        adc.self_offset_cal()
        vals = []
        for _ in range(200):
            v, _, st = adc.convert(MUX_AINCOM, MUX_AINCOM)
            vals.append(v)
        mean = statistics.fmean(vals)
        rms = statistics.pstdev(vals)
        print(f"  ค่าเฉลี่ย = {mean*1e6:9.2f} µV")
        print(f"  RMS noise = {rms*1e6:9.2f} µV   (pk-pk ≈ {(max(vals)-min(vals))*1e6:.2f} µV)")
        print(f"  FSR       = ±{adc.fsr*1000:.2f} mV")
        flags = ADS1263.decode_status(st)
        print(f"  STATUS    = 0x{st:02X} {flags if flags else ''}")
        print("  ค่าที่ดีควรอยู่ระดับไม่เกิน 1 µV ถ้าได้หลัก mV แปลว่าอินพุตลอยอยู่")

        step(6, "อ่าน 3 แกนจริง + วัดความเร็วการสแกน")
        n = 200
        t0 = time.perf_counter()
        buf = {k: [] for k in C.CHANNELS}
        for _ in range(n):
            s = adc.scan(C.CHANNELS)
            for k, v in s.items():
                buf[k].append(v)
        dt = time.perf_counter() - t0
        print(f"  สแกน {n} รอบ x {len(C.CHANNELS)} ช่อง ใน {dt:.3f} s")
        print(f"  -> {n/dt:.1f} รอบ/วินาที  (อัตราการอ่านค่าต่อแกน = {n/dt:.1f} Hz, "
              f"Nyquist ≈ {n/dt/2:.1f} Hz)\n")
        for k, v in buf.items():
            dc = statistics.fmean(v)
            ac = statistics.pstdev(v)
            vel = ac / C.GEO_SENS * 1000.0     # mm/s RMS
            print(f"  {k}: DC = {dc*1000:8.3f} mV | AC(RMS) = {ac*1e6:9.2f} µV "
                  f"| ≈ {vel:7.4f} mm/s RMS")
        print("\n  ลองเคาะโต๊ะเบา ๆ แล้วรันซ้ำ — ค่า AC ควรกระโดดขึ้นชัดเจน")
        print("  ถ้า DC ติดขอบ FSR (±%.1f mV) แปลว่าขาด bias resistor หรือ gain สูงเกินไป"
              % (adc.fsr * 1000))

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
