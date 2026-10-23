#!/usr/bin/env python3
"""
raw_check.py — ดูข้อมูลดิบจาก ADS1263 ตั้งแต่ระดับไบต์บนสาย SPI

โหมด:
  python3 tests/raw_check.py            แกะ 1 การอ่านของทุกแกน ให้เห็นทุกไบต์
  python3 tests/raw_check.py stream Y   ไหลค่าดิบของแกนเดียวแบบสด (Ctrl+C ออก)
  python3 tests/raw_check.py stats Y    เก็บ 500 ตัวอย่าง แล้วสรุปสถิติ + ENOB
  python3 tests/raw_check.py stats Y 2000   กำหนดจำนวนตัวอย่างเอง
"""
import _path  # noqa
from _guard import require_exclusive
import math
import statistics
import subprocess
import sys
import time

import config as C
from drivers.ads1263 import ADS1263, CMD_RDATA1, MUX_AINCOM

BAR = "=" * 70
FULL = 1 << 31          # ค่าเต็มสเกลของเลข 32 บิตมีเครื่องหมาย


def read_verbose(adc, p, n):
    """อ่าน 1 ค่า แล้วคืนทุกอย่างที่เกิดขึ้นบนสาย"""
    adc.set_mux(p, n)
    adc._pulse_start()
    wait = adc.wait_drdy()
    tx = [CMD_RDATA1] + [0x00] * 6
    rx = adc._xfer(tx)
    status = rx[1]
    data = rx[2:6]
    chk_rx = rx[6]
    chk_calc = (sum(data) + 0x9B) & 0xFF
    raw = (data[0] << 24) | (data[1] << 16) | (data[2] << 8) | data[3]
    if raw & 0x80000000:
        raw -= 1 << 32
    return {"tx": tx, "rx": rx, "status": status, "data": data,
            "chk_rx": chk_rx, "chk_calc": chk_calc, "raw": raw,
            "volt": raw * adc.fsr / FULL, "wait_ms": wait * 1000}


def open_adc():
    adc = ADS1263(bus=C.ADS_BUS, dev=C.ADS_DEV, speed_hz=C.ADS_SPI_HZ,
                  pin_reset=C.ADS_PIN_RESET, pin_start=C.ADS_PIN_START,
                  pin_drdy=C.ADS_PIN_DRDY, vref=C.ADS_VREF)
    adc.reset()
    name, rev, idreg = adc.chip_id()
    adc.configure(gain=C.ADS_GAIN, rate=C.ADS_RATE,
                  filt=C.ADS_FILTER, one_shot=True)
    return adc, name, rev, idreg


# ----------------------------------------------------------------- โหมด 1
def mode_detail(adc):
    print(f"\n{BAR}\nแกะการอ่าน 1 ครั้งของแต่ละแกน\n{BAR}")
    print(f"gain {C.ADS_GAIN}   rate {C.ADS_RATE} SPS   filter {C.ADS_FILTER}   "
          f"VREF {C.ADS_VREF} V   FSR ±{adc.fsr*1000:.3f} mV")
    print(f"1 LSB = {adc.fsr / FULL * 1e9:.4f} nV\n")

    for name, (p, q) in list(C.CHANNELS.items()) + [("AINCOM ลัดวงจร",
                                                     (MUX_AINCOM, MUX_AINCOM))]:
        r = read_verbose(adc, p, q)
        print(f"--- {name}   (MUXP={p} MUXN={q}) ---")
        print(f"   Pi ส่งออก : {' '.join(f'{b:02X}' for b in r['tx'])}")
        print(f"   Pi รับเข้า: {' '.join(f'{b:02X}' for b in r['rx'])}")
        print(f"               --  ST  D3 D2 D1 D0  CK")
        print(f"   รอ DRDY   : {r['wait_ms']:.3f} ms")
        flags = ADS1263.decode_status(r["status"])
        print(f"   STATUS    : 0x{r['status']:02X}  {flags if flags else '(ปกติ)'}")
        ok = r["chk_rx"] == r["chk_calc"]
        print(f"   Checksum  : รับ 0x{r['chk_rx']:02X}  คำนวณ 0x{r['chk_calc']:02X}  "
              f"{'ตรง' if ok else '<<< ไม่ตรง!'}")
        print(f"   ข้อมูลดิบ : {' '.join(f'{b:02X}' for b in r['data'])}  "
              f"= {r['raw']:+12d}  ({r['raw']/FULL*100:+7.3f}% ของเต็มสเกล)")
        print(f"   แรงดัน    : {r['volt']*1000:+12.6f} mV")
        print(f"   ความเร็ว  : {r['volt']/C.GEO_SENS*1e6:+12.2f} um/s\n")


# ----------------------------------------------------------------- โหมด 2
def mode_stream(adc, axis):
    p, q = C.CHANNELS[axis]
    print(f"\nไหลค่าดิบของแกน {axis} (AIN{p}-AIN{q})   Ctrl+C เพื่อออก")
    print(f"FSR ±{adc.fsr*1000:.3f} mV   1 LSB = {adc.fsr/FULL*1e9:.4f} nV\n")
    print(f"{'ครั้งที่':>8}  {'ไบต์ข้อมูล':<12} {'ค่าดิบ':>13} {'%FS':>8} "
          f"{'mV':>12} {'um/s':>12}  ST")
    print("-" * 78)
    i = 0
    try:
        while True:
            r = read_verbose(adc, p, q)
            i += 1
            bad = "" if r["chk_rx"] == r["chk_calc"] else "  CHK!"
            print(f"{i:8d}  {' '.join(f'{b:02X}' for b in r['data']):<12} "
                  f"{r['raw']:13d} {r['raw']/FULL*100:+8.3f} "
                  f"{r['volt']*1000:+12.6f} {r['volt']/C.GEO_SENS*1e6:+12.2f}  "
                  f"{r['status']:02X}{bad}")
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nออกแล้ว")


# ----------------------------------------------------------------- โหมด 3
def mode_stats(adc, axis, count):
    p, q = C.CHANNELS[axis]
    print(f"\n{BAR}\nเก็บ {count} ตัวอย่างจากแกน {axis} (AIN{p}-AIN{q})\n{BAR}")
    raws, bad = [], 0
    t0 = time.perf_counter()
    for _ in range(count):
        r = read_verbose(adc, p, q)
        raws.append(r["raw"])
        if r["chk_rx"] != r["chk_calc"]:
            bad += 1
    dt = time.perf_counter() - t0

    mean = statistics.fmean(raws)
    sd = statistics.pstdev(raws)
    lo, hi = min(raws), max(raws)
    lsb = adc.fsr / FULL

    print(f"   อัตราที่ทำได้  : {count/dt:8.1f} ครั้ง/วินาที")
    print(f"   checksum เสีย  : {bad} / {count} "
          f"{'(ดี)' if bad == 0 else '<<< มีปัญหาสาย/ความเร็ว SPI'}")
    print()
    print(f"   {'':14}{'counts':>16}{'mV':>16}{'um/s':>14}")
    print(f"   {'ค่าเฉลี่ย':<14}{mean:16.1f}{mean*lsb*1e3:16.6f}"
          f"{mean*lsb/C.GEO_SENS*1e6:14.2f}")
    print(f"   {'ต่ำสุด':<14}{lo:16d}{lo*lsb*1e3:16.6f}"
          f"{lo*lsb/C.GEO_SENS*1e6:14.2f}")
    print(f"   {'สูงสุด':<14}{hi:16d}{hi*lsb*1e3:16.6f}"
          f"{hi*lsb/C.GEO_SENS*1e6:14.2f}")
    print(f"   {'RMS (noise)':<14}{sd:16.1f}{sd*lsb*1e3:16.6f}"
          f"{sd*lsb/C.GEO_SENS*1e6:14.2f}")
    print(f"   {'pk-pk':<14}{hi-lo:16d}{(hi-lo)*lsb*1e3:16.6f}"
          f"{(hi-lo)*lsb/C.GEO_SENS*1e6:14.2f}")

    if sd > 0:
        enob = math.log2(2 * FULL / (sd * 2 * math.sqrt(2)))
        nfree = math.log2(2 * FULL / max(hi - lo, 1))
        print(f"\n   ENOB (RMS)        : {enob:5.2f} บิต")
        print(f"   Noise-free bits   : {nfree:5.2f} บิต")
        print(f"   บิตล่างที่เป็น noise: {math.log2(max(sd,1)):5.2f} บิต")

    print(f"\n   กระจายตัวรอบค่าเฉลี่ย (1 ช่อง = {sd/4:,.0f} counts)")
    step = max(sd / 4, 1)
    hist = {}
    for v in raws:
        k = int(round((v - mean) / step))
        hist[k] = hist.get(k, 0) + 1
    for k in sorted(hist):
        n = hist[k]
        print(f"   {k*step:+12,.0f} | {'#' * max(1, int(n / max(hist.values()) * 46))} {n}")


def main():
    args = sys.argv[1:]
    mode = args[0] if args else "detail"
    require_exclusive((C.ADS_PIN_DRDY, C.ADS_PIN_START, C.ADS_PIN_RESET),
                      "ชิป ADC")
    adc, name, rev, idreg = open_adc()
    try:
        print(f"\nชิป: {name} rev {rev}  (ID register = 0x{idreg:02X})")
        if mode == "stream":
            mode_stream(adc, args[1] if len(args) > 1 else "Y")
        elif mode == "stats":
            axis = args[1] if len(args) > 1 else "Y"
            cnt = int(args[2]) if len(args) > 2 else 500
            mode_stats(adc, axis, cnt)
        else:
            mode_detail(adc)
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
