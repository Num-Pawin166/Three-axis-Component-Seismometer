#!/usr/bin/env python3
"""
t3c_app_display.py — หาว่าทำไมจอขึ้นภาพตอนทดสอบ แต่ขาวตอนรันแอปจริง

t3b พิสูจน์แล้วว่าไดรเวอร์จอกับลำดับคำสั่งไม่มีปัญหา
แอปจริงต่างจาก t3b อยู่สามอย่าง สคริปต์นี้เติมทีละอย่างแล้วดูว่าพังตอนไหน

  ขั้น 1  จออย่างเดียว วาดซ้ำ ๆ
  ขั้น 2  เปิดทัชสกรีนบนบัสเดียวกันด้วย แล้วสลับอ่านทัชกับวาดจอ
  ขั้น 3  เพิ่มเธรดที่วนเปิด/ปิด ADS1263 ทุก 2 วินาที (เลียนแบบตอน ADC พัง)

แต่ละขั้นเขียนเลขขั้นตัวโต ๆ พร้อมตัวนับเฟรมบนจอ
ดูที่จอแล้วจำว่า "เลขหยุดเดินตอนขั้นไหน"

รัน:  python3 tests/t3c_app_display.py
"""
import _path  # noqa
from _guard import require_exclusive
import threading
import time

from PIL import Image, ImageDraw

import config as C
from drivers.st7796 import ST7796, load_font
from drivers.xpt2046 import XPT2046

BG = [(25, 40, 80), (20, 70, 50), (80, 35, 30)]
STAGE_SEC = 12.0
stop_flag = threading.Event()


def adc_churn(log):
    """เลียนแบบ Sampler ตอน ADC พัง: วนสร้าง/รีเซ็ต/ปิด ทุก 2 วินาที"""
    from drivers.ads1263 import ADS1263
    n = 0
    while not stop_flag.is_set():
        adc = None
        try:
            adc = ADS1263(bus=C.ADS_BUS, dev=C.ADS_DEV, speed_hz=C.ADS_SPI_HZ,
                          pin_reset=C.ADS_PIN_RESET, pin_start=C.ADS_PIN_START,
                          pin_drdy=C.ADS_PIN_DRDY, vref=C.ADS_VREF)
            adc.reset()
            adc.configure(gain=C.ADS_GAIN, rate=C.ADS_RATE,
                          filt=C.ADS_FILTER, one_shot=True)
            adc.convert(0, 1)
        except Exception as e:
            log.append(type(e).__name__)
        finally:
            if adc is not None:
                try:
                    adc.close()
                except Exception:
                    pass
        n += 1
        stop_flag.wait(2.0)
    log.append(f"วนทั้งหมด {n} รอบ")


def draw(tft, fonts, stage, frame, note):
    f1, f2 = fonts
    img = Image.new("RGB", (tft.width, tft.height), BG[stage - 1])
    d = ImageDraw.Draw(img)
    d.rectangle([3, 3, tft.width - 4, tft.height - 4], outline=(255, 255, 255), width=3)
    s = str(stage)
    tw = d.textlength(s, font=f1)
    d.text(((tft.width - tw) / 2, 50), s, font=f1, fill=(255, 255, 255))
    d.text((16, 14), f"ขั้นที่ {stage}", font=f2, fill=(255, 255, 255))
    d.text((16, tft.height - 60), note, font=f2, fill=(220, 230, 245))
    d.text((16, tft.height - 32), f"เฟรม {frame}", font=f2, fill=(255, 235, 140))
    tft.blit(img)


def main():
    require_exclusive((C.TFT_PIN_DC, C.TFT_PIN_RST,
                       C.ADS_PIN_DRDY, C.ADS_PIN_START, C.ADS_PIN_RESET),
                      "จอและ ADC")
    print("=" * 66)
    print("มองที่จอตลอด — สังเกตว่า 'ตัวนับเฟรม' หยุดเดินตอนขั้นไหน")
    print("ขั้นละ 12 วินาที")
    print("=" * 66)

    tft = ST7796(bus=C.TFT_BUS, dev=C.TFT_DEV, speed_hz=C.TFT_SPI_HZ,
                 pin_dc=C.TFT_PIN_DC, pin_rst=C.TFT_PIN_RST,
                 rotation=C.TFT_ROTATION, invert=C.TFT_INVERT, bgr=C.TFT_BGR)
    fonts = (load_font(130), load_font(20))
    ts = None
    churn = None
    log = []
    frame = 0

    try:
        # ---------------------------------------------------- ขั้น 1
        print("\n[ขั้น 1] จออย่างเดียว")
        t0 = time.time()
        while time.time() - t0 < STAGE_SEC:
            frame += 1
            draw(tft, fonts, 1, frame, "จอล้วน ไม่มีอย่างอื่น")
            time.sleep(1 / 8)
        print(f"   วาดไป {frame} เฟรม")

        # ---------------------------------------------------- ขั้น 2
        print("\n[ขั้น 2] เพิ่มทัชสกรีนบนบัส SPI1 เดียวกัน")
        ts = XPT2046(bus=C.TS_BUS, dev=C.TS_DEV, speed_hz=C.TS_SPI_HZ,
                     pin_irq=C.TS_PIN_IRQ, cal_file=C.TS_CAL_FILE,
                     width=tft.width, height=tft.height)
        print("   เปิดทัชแล้ว")
        t0, f0 = time.time(), frame
        while time.time() - t0 < STAGE_SEC:
            frame += 1
            try:
                ts.read_touch()
            except Exception as e:
                print("   touch error:", e)
            draw(tft, fonts, 2, frame, "จอ + ทัชสกรีน บัสเดียวกัน")
            time.sleep(1 / 8)
        print(f"   วาดไป {frame - f0} เฟรม")

        # ---------------------------------------------------- ขั้น 3
        print("\n[ขั้น 3] เพิ่มเธรด ADC ที่วนพังทุก 2 วินาที")
        churn = threading.Thread(target=adc_churn, args=(log,), daemon=True)
        churn.start()
        t0, f0 = time.time(), frame
        while time.time() - t0 < STAGE_SEC * 2:
            frame += 1
            try:
                ts.read_touch()
            except Exception as e:
                print("   touch error:", e)
            draw(tft, fonts, 3, frame, "จอ + ทัช + เธรด ADC ที่พัง")
            time.sleep(1 / 8)
        print(f"   วาดไป {frame - f0} เฟรม")

    finally:
        stop_flag.set()
        if churn is not None:
            churn.join(timeout=4)
        if ts is not None:
            try:
                ts.close()
            except Exception:
                pass
        try:
            tft.fill((0, 0, 0))
            tft.close()
        except Exception:
            pass

    print("\n" + "=" * 66)
    print("สรุปจากเธรด ADC:", ", ".join(log[-4:]) if log else "ไม่มี")
    print()
    print("ถ้าตัวนับเฟรมเดินครบทั้ง 3 ขั้น -> จอไม่ได้มีปัญหา ต้องดูที่อื่นในแอป")
    print("ถ้าหยุดเดินตอนขั้น 2      -> ทัชสกรีนกวนบัส SPI1")
    print("ถ้าหยุดเดินตอนขั้น 3      -> เธรด ADC ที่วนพังไปกวนจอ")
    print("=" * 66)


if __name__ == "__main__":
    main()
