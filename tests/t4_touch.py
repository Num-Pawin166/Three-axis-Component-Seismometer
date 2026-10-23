#!/usr/bin/env python3
"""
t4_touch.py — คาลิเบรตและทดสอบทัชสกรีน XPT2046

จุดสำคัญ: กากบาทวาดห่างจากขอบจอ 30 พิกเซล ไม่ได้อยู่ที่มุมจริง
โปรแกรมจึงต้อง "ยืดเส้นตรง" ออกไปถึงขอบจอก่อนบันทึกค่า
ถ้าเอาค่าดิบที่กากบาทไปใช้เป็นค่าขอบตรง ๆ พิกัดจะเพี้ยนราว 14%
และปุ่มแถวล่างจะกดไม่โดน

รัน:  python3 tests/t4_touch.py          คาลิเบรตใหม่แล้วบันทึกไฟล์
      python3 tests/t4_touch.py check    ข้ามการคาลิเบรต ไปทดสอบค่าที่มีอยู่
"""
import _path  # noqa
from _guard import require_exclusive
import json
import sys
import time

from PIL import Image, ImageDraw

import config as C
from drivers.st7796 import ST7796, load_font, font_has_thai
from drivers.xpt2046 import XPT2046

MARGIN = 30          # ระยะจากขอบจอถึงกึ่งกลางกากบาท (พิกเซล)
LINE = "-" * 62


def crosshair(tft, fonts, px, py, idx, total, thai):
    f_mid, f_sm = fonts
    img = Image.new("RGB", (tft.width, tft.height), (8, 10, 14))
    d = ImageDraw.Draw(img)
    d.line([(px - 22, py), (px + 22, py)], fill=(255, 220, 90), width=2)
    d.line([(px, py - 22), (px, py + 22)], fill=(255, 220, 90), width=2)
    d.ellipse([px - 7, py - 7, px + 7, py + 7], outline=(255, 220, 90), width=2)
    msg = f"แตะตรงกลางกากบาท  ({idx}/{total})" if thai else f"Tap the crosshair  ({idx}/{total})"
    tw = d.textlength(msg, font=f_mid)
    d.text(((tft.width - tw) / 2, tft.height / 2 - 12), msg, font=f_mid,
           fill=(235, 240, 250))
    tip = "ใช้ปลายนิ้วหรือปากกาทัช กดค้างสักครู่" if thai else "Hold briefly with a stylus or fingertip"
    tw = d.textlength(tip, font=f_sm)
    d.text(((tft.width - tw) / 2, tft.height / 2 + 14), tip, font=f_sm, fill=(130, 140, 160))
    tft.blit(img)


def solve3(A, b):
    """แก้ระบบสมการ 3x3 ด้วยการกำจัดแบบเกาส์ (มีการสลับแถวกันหารด้วยศูนย์)"""
    m = [list(A[i]) + [b[i]] for i in range(3)]
    for col in range(3):
        piv = max(range(col, 3), key=lambda r: abs(m[r][col]))
        if abs(m[piv][col]) < 1e-12:
            return None
        m[col], m[piv] = m[piv], m[col]
        p = m[col][col]
        m[col] = [v / p for v in m[col]]
        for r in range(3):
            if r != col and m[r][col]:
                f = m[r][col]
                m[r] = [v - f * w for v, w in zip(m[r], m[col])]
    return [m[i][3] for i in range(3)]


def affine_fit(raws, vals):
    """หา (a, b, c) ที่ทำให้  a*rx + b*ry + c  ใกล้ vals ที่สุด (กำลังสองน้อยสุด)

    พจน์ไขว้สำคัญมาก เพราะแกนของแผ่นทัชไม่ได้ตั้งฉากกับแกนจอพอดี
    ถ้ายืดทีละแกนแยกกันแบบเดิม ความเอียงนี้จะโผล่เป็นความคลาดที่มุมจอเสมอ
    """
    n = len(raws)
    sxx = sum(r[0] * r[0] for r in raws)
    sxy = sum(r[0] * r[1] for r in raws)
    syy = sum(r[1] * r[1] for r in raws)
    sx = sum(r[0] for r in raws)
    sy = sum(r[1] for r in raws)
    A = [[sxx, sxy, sx], [sxy, syy, sy], [sx, sy, float(n)]]
    b = [sum(r[0] * v for r, v in zip(raws, vals)),
         sum(r[1] * v for r, v in zip(raws, vals)),
         sum(vals)]
    return solve3(A, b)


def sample_point(ts, settle=0.20, n=9, timeout=30.0):
    """รอให้แตะ แล้วค่อยเก็บค่า — ไม่เก็บทันทีที่สัมผัส

    จังหวะแรกที่นิ้วแตะแผ่นตัวต้านทาน ความต้านทานสัมผัสยังไม่นิ่ง
    ค่าที่อ่านได้ตอนนั้นเพี้ยนได้หลายสิบพิกเซล จึงต้องรอให้นิ่งก่อน
    แล้วเก็บหลายครั้งเอาค่ากลาง คืน (x, y, การกระจายของค่า)
    """
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if ts.raw(5) is not None:
            break
        time.sleep(0.01)
    else:
        return None
    time.sleep(settle)
    xs, ys = [], []
    for _ in range(n):
        r = ts.raw(9)
        if r is not None:
            xs.append(r[0])
            ys.append(r[1])
        time.sleep(0.02)
    if len(xs) < max(3, n // 2):
        return None
    xs.sort()
    ys.sort()
    return (xs[len(xs) // 2], ys[len(ys) // 2],
            max(max(xs) - min(xs), max(ys) - min(ys)))


def calibrate(tft, ts, fonts, thai):
    W, H = tft.width, tft.height
    pts = [(MARGIN, MARGIN), (W - MARGIN, MARGIN),
           (W - MARGIN, H - MARGIN), (MARGIN, H - MARGIN), (W // 2, H // 2)]
    raw = []

    print(f"\n{LINE}\nคาลิเบรต — แตะกากบาททีละจุด {len(pts)} จุด\n{LINE}")
    print("   กดค้างไว้จนกว่ากากบาทจะเปลี่ยนจุด (ราวครึ่งวินาที) อย่าปล่อยเร็วเกินไป")
    for i, (px, py) in enumerate(pts, 1):
        crosshair(tft, fonts, px, py, i, len(pts), thai)
        while ts.pressed():                   # รอปล่อยนิ้วจากจุดก่อนหน้า
            time.sleep(0.02)
        time.sleep(0.25)
        got = sample_point(ts)
        if got is None:
            print("   หมดเวลารอการแตะ — ยกเลิก")
            return None
        rx, ry, spread = got
        raw.append((float(rx), float(ry)))
        warn = "   <- ค่าแกว่งมาก ลองกดนิ่ง ๆ กว่านี้" if spread > 150 else ""
        print(f"   จุดที่ {i}  หน้าจอ ({px:3d},{py:3d})   "
              f"ค่าดิบ ({rx:4d},{ry:4d})  แกว่ง {spread:4d}{warn}")
        while ts.pressed():
            time.sleep(0.02)

    mx = affine_fit(raw, [float(p[0]) for p in pts])
    my = affine_fit(raw, [float(p[1]) for p in pts])
    if mx is None or my is None:
        print("   คำนวณไม่ได้ — ค่าที่แตะมาอาจอยู่ซ้อนกันหมด ลองใหม่")
        return None

    print("\n   สูตรที่ได้")
    print(f"      แกนนอน = {mx[0]:+.6f}*ดิบX {mx[1]:+.6f}*ดิบY {mx[2]:+.2f}")
    print(f"      แกนตั้ง = {my[0]:+.6f}*ดิบX {my[1]:+.6f}*ดิบY {my[2]:+.2f}")

    errs = []
    print("\n   ย้อนกลับไปเช็กกับจุดที่แตะมา")
    for (px, py), (rx, ry) in zip(pts, raw):
        gx = mx[0] * rx + mx[1] * ry + mx[2]
        gy = my[0] * rx + my[1] * ry + my[2]
        e = ((gx - px) ** 2 + (gy - py) ** 2) ** 0.5
        errs.append(e)
        print(f"      ({px:3d},{py:3d}) -> ({gx:6.1f},{gy:6.1f})   คลาด {e:5.1f} px")
    avg = sum(errs) / len(errs)
    print(f"      เฉลี่ย {avg:.1f} px  สูงสุด {max(errs):.1f} px")
    if avg > 12:
        print("      ยังสูงอยู่ — มักเกิดจากกดไม่ตรงกลางกากบาท หรือปล่อยนิ้วเร็วไป")
        print("      แนะนำให้รันใหม่อีกรอบ ใช้ปากกาทัชจะแม่นกว่านิ้วมาก")

    cal = {"affine": [list(mx), list(my)], "w": W, "h": H}
    ts.save_cal(cal)
    print(f"\n   บันทึกลง {ts.cal_file} แล้ว")
    return cal


def verify(tft, ts, fonts, thai):
    W, H = tft.width, tft.height
    f_mid, f_sm = fonts
    targets = [(W // 2, H // 2), (60, 60), (W - 60, H - 60),
               (W // 2, H - 18), (60, H - 18), (W - 60, H - 18)]
    print(f"\n{LINE}\nทดสอบความแม่น — แตะตามจุดที่ขึ้นบนจอ\n{LINE}")
    print("   สามจุดสุดท้ายอยู่แถวล่างสุด ตรงตำแหน่งปุ่มของโปรแกรมจริง")
    errs = []
    for i, (tx, ty) in enumerate(targets, 1):
        img = Image.new("RGB", (W, H), (8, 10, 14))
        d = ImageDraw.Draw(img)
        d.ellipse([tx - 13, ty - 13, tx + 13, ty + 13], outline=(90, 220, 255), width=3)
        d.ellipse([tx - 2, ty - 2, tx + 2, ty + 2], fill=(90, 220, 255))
        msg = f"แตะวงกลม ({i}/{len(targets)})" if thai else f"Tap the circle ({i}/{len(targets)})"
        d.text((10, 8), msg, font=f_mid, fill=(220, 228, 240))
        tft.blit(img)
        while ts.pressed():
            time.sleep(0.02)
        time.sleep(0.2)
        pos = None
        t0 = time.monotonic()
        while time.monotonic() - t0 < 30:
            pos = ts.read_touch(9)
            if pos:
                break
            time.sleep(0.01)
        if not pos:
            print("   หมดเวลารอ")
            continue
        ex = ((pos[0] - tx) ** 2 + (pos[1] - ty) ** 2) ** 0.5
        errs.append(ex)
        mark = "ดี" if ex <= 12 else ("พอใช้" if ex <= 25 else "เพี้ยนมาก")
        print(f"   เป้า ({tx:3d},{ty:3d})  อ่านได้ ({pos[0]:3d},{pos[1]:3d})  "
              f"คลาด {ex:5.1f} px  {mark}")
        while ts.pressed():
            time.sleep(0.02)
    if errs:
        print(f"\n   ความคลาดเคลื่อนเฉลี่ย {sum(errs)/len(errs):.1f} px  "
              f"สูงสุด {max(errs):.1f} px")
        print("   ถ้าเกิน 20 px โดยเฉพาะที่แถวล่าง ให้คาลิเบรตใหม่โดยแตะให้ตรงกลางกากบาทกว่าเดิม")


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "cal"
    require_exclusive((C.TFT_PIN_DC, C.TFT_PIN_RST), "จอและทัชสกรีน")
    tft = ST7796(bus=C.TFT_BUS, dev=C.TFT_DEV, speed_hz=C.TFT_SPI_HZ,
                 pin_dc=C.TFT_PIN_DC, pin_rst=C.TFT_PIN_RST,
                 rotation=C.TFT_ROTATION, invert=C.TFT_INVERT, bgr=C.TFT_BGR)
    ts = XPT2046(bus=C.TS_BUS, dev=C.TS_DEV, speed_hz=C.TS_SPI_HZ,
                 pin_irq=C.TS_PIN_IRQ, cal_file=C.TS_CAL_FILE,
                 width=tft.width, height=tft.height)
    fonts = (load_font(18), load_font(13))
    thai = font_has_thai(fonts[0])
    try:
        lvl = ts.irq_level()
        print(f"ขา T_IRQ (GPIO {C.TS_PIN_IRQ}) ตอนนี้อ่านได้ {lvl} "
              f"— ใช้ดูประกอบเท่านั้น โปรแกรมอ่านสถานะจากชิปโดยตรง")
        print(f"ค่าคาลิเบรตที่ใช้อยู่: {json.dumps(ts.cal)}")
        if mode != "check":
            if calibrate(tft, ts, fonts, thai) is None:
                return
        verify(tft, ts, fonts, thai)
        tft.fill((0, 0, 0))
    except KeyboardInterrupt:
        print("\nยกเลิก")
    finally:
        ts.close()
        tft.close()
        try:
            from gpiozero import Device
            if Device.pin_factory is not None:
                Device.pin_factory.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
