#!/usr/bin/env python3
"""
app_fft.py — จอเฝ้าระวังแรงสั่นสะเทือน 3 แกน

  หน้า LIVE      สเปกตรัม FFT แยกช่อง X / Y / Z + นาฬิกา (แตะกราฟแกนไหนก็เข้าไปดูแกนนั้น)
  หน้า LIVE X/Y/Z  แยกความถี่ของแกนที่เลือกแบบสด ๆ ว่ามาจากคนหรือธรรมชาติ
  หน้า HISTORY     ประวัติความเร็วอนุภาคสูงสุดรายชั่วโมง (แตะแท่งกราฟเพื่อดูรายละเอียด)
  หน้า DETAIL    แยกแหล่งกำเนิดของช่วงเวลาที่เลือก: กิจกรรมมนุษย์ หรือ ธรรมชาติ
  หน้า SUMMARY   ตัวเลขสรุป ตอนนี้ / 1 ชม. / 24 ชม.

  แตะปุ่มด้านล่างเพื่อเปลี่ยนหน้า และบันทึกสถิติลง data/history.csv ทุกนาที
  ตรวจหาเซ็นเซอร์อัตโนมัติ สแกนซ้ำทุก 60 วิ ถ้ายังมีแกนขาด
  ชดเชยการตอบสนองของ geophone ให้ค่าที่ต่ำกว่า 4.5 Hz ถูกต้อง (ดูหัวข้อ GEO_* ข้างล่าง)

รัน:  python3 app_fft.py        ออก: Ctrl+C
"""
import csv
import os
import statistics
import threading
import time
import traceback
from collections import deque
from datetime import datetime

import numpy as np
from PIL import Image, ImageDraw

import config as C
from drivers.ads1263 import ADS1263
from drivers.st7796 import ST7796, load_font, font_has_thai, thai_shaping_ok
from drivers.xpt2046 import XPT2046

AXES = [("X", 0, 1), ("Y", 2, 3), ("Z", 4, 5)]
NAMES = [a[0] for a in AXES]
COLORS = {"X": (255, 95, 95), "Y": (95, 235, 140), "Z": (110, 175, 255)}
GREY = (95, 100, 112)
DIMTXT = (128, 138, 158)

# ---------------- ตั้งค่า ----------------
N = 1024                 # ขนาดบัฟเฟอร์ FFT
RESCAN = 60.0            # สแกนหาเซ็นเซอร์ซ้ำทุกกี่วินาที
FPS = 8.0

PAGES = ["live", "history", "summary"]
# ชื่อหน้าที่แสดงบนปุ่มและบนหัวจอ — ไทยก่อน ถ้าฟอนต์ไม่มีอักษรไทยค่อยใช้อังกฤษ
PAGE_TH = {"live": "สด", "history": "ย้อนหลัง", "summary": "สรุป",
           "axis": "แยกแกน", "bucket": "รายละเอียด"}
PAGE_EN = {"live": "LIVE", "history": "HISTORY", "summary": "SUMMARY",
           "axis": "AXIS", "bucket": "DETAIL"}
THAI = True              # ตั้งค่าจริงตอนเริ่มโปรแกรม หลังโหลดฟอนต์แล้ว


def L(th, en):
    """เลือกข้อความตามฟอนต์ที่มี — ไทยถ้าวาดได้ ไม่งั้นอังกฤษ"""
    return th if THAI else en


def page_name(key):
    """ชื่อหน้าสำหรับแสดงผล

    เคยเขียนพลาดเป็น PAGE_TH[key].upper() ตอนไม่มีฟอนต์ไทย
    ซึ่งไม่ได้ผล เพราะอักษรไทยไม่มีตัวพิมพ์ใหญ่ .upper() จึงคืนค่าเดิม
    ปุ่มเลยยังเป็นภาษาไทยและขึ้นเป็นกล่องสี่เหลี่ยม ทั้งที่ข้อความอื่นเป็นอังกฤษแล้ว
    ต้องแยกตารางอังกฤษไว้ต่างหาก
    """
    return PAGE_TH.get(key, key) if THAI else PAGE_EN.get(key, key.upper())
AUTO_PAGE = False        # True = สลับหน้าเองอัตโนมัติ, False = กดเลือกเอง
AUTO_SEC = 10.0          # สลับหน้าทุกกี่วินาที
MANUAL_HOLD = 60.0       # แตะจอแล้วหยุดสลับกี่วินาที
BTN_H = 42               # ความสูงแถบปุ่ม (0 = ซ่อนปุ่ม)
                         # 34 เตี้ยไปสำหรับนิ้ว — ปลายนิ้วกว้างราว 8 มม. = 40 พิกเซล
                         # บนจอนี้ ปุ่มจึงควรสูงกว่านั้นเผื่อความคลาดของแผ่นทัช
TOUCH_DEBUG = True       # โชว์ไฟบอกสถานะทัชบนหัวจอ (ใช้ไล่ปัญหาทัชไม่ตอบสนอง)
TOUCH_POLL = 0.04        # อ่านทัชทุกกี่วินาที (อ่านตรงจากชิป ไม่ใช้ขา IRQ)
TOUCH_SAMPLES = 5        # อ่านกี่ครั้งต่อหนึ่งจุด แล้วเอาค่ากลาง (มากขึ้น = นิ่งขึ้น แต่ช้าลง)
TOUCH_RELEASE = 3        # ต้องอ่านไม่เจอนิ้วติดกันกี่ครั้ง ถึงนับว่าปล่อยนิ้วแล้ว
TOUCH_DEBOUNCE = 0.35    # เว้นระยะอย่างน้อยกี่วินาที ระหว่างการแตะสองครั้งที่นับผล
LOG_PERIOD = 60.0        # บันทึกสถิติลงไฟล์ทุกกี่วินาที
HIST_FILE = os.path.join(C.DATA_DIR, "history.csv")
HIST_MAX = 2880          # เก็บในหน่วยความจำกี่แถว (2880 นาที = 48 ชม.)
HISTORY_HOURS = 6.0        # หน้า HISTORY ย้อนหลังกี่ชั่วโมง

# ---- แยกแหล่งกำเนิดการสั่น: กิจกรรมมนุษย์ หรือ ธรรมชาติ ----
# งานวิจัยด้านแผ่นดินไหวเรียกการสั่นจากกิจกรรมมนุษย์ว่า cultural noise
# ซึ่งกระจุกตัวอยู่เหนือ 8-10 Hz ขึ้นไป (เครื่องจักร ปั๊มน้ำ แอร์ รถวิ่ง)
# ส่วนคลื่นจากแผ่นดินไหวที่เดินทางมาไกลจะเหลือพลังงานอยู่ในย่านต่ำกว่านั้น
#
# ตัวช่วยแยกตัวที่สอง คือสัดส่วนการเคลื่อนที่แกนราบต่อแกนตั้ง (H/V)
#   แผ่นดินไหว  -> คลื่น S และคลื่นผิวทำให้พื้นเคลื่อนในแนวราบมากกว่าแนวตั้ง (H/V > 1)
#   คนหรือเครื่องจักรที่อยู่ใกล้ -> แรงกดลงบนพื้น ทำให้แนวตั้งเป็นหลัก (H/V < 1)
SRC_ENABLE = True
SRC_NAT = (1.0, 8.0)     # ย่าน "ธรรมชาติ" (Hz) — ขอบล่างควรไม่ต่ำกว่า GEO_FTARGET
SRC_HUM = (8.0, 50.0)    # ย่าน "กิจกรรมมนุษย์" (Hz) — ขอบบนถูกจำกัดด้วย fs/2 อัตโนมัติ
SRC_VERT = "Z"           # แกนที่ติดตั้งในแนวตั้ง (ใช้คำนวณ H/V)
SRC_HV_NAT = 1.40        # H/V ตั้งแต่เท่านี้ขึ้นไป = ชี้ไปทางธรรมชาติเต็มที่
SRC_HV_HUM = 0.60        # H/V ต่ำกว่านี้ = ชี้ไปทางกิจกรรมมนุษย์เต็มที่
SRC_W_FREQ = 0.60        # น้ำหนักของย่านความถี่ในการตัดสิน (ที่เหลือเป็นของ H/V)
                         # ต้องเหลือให้ H/V มากพอที่จะดึงผลขึ้นมาเป็น "ปนกัน" ได้เอง
                         # เพราะคนเดิน (ก้าวละ ~2 Hz) ตกอยู่ในย่านต่ำเหมือนแผ่นดินไหว
                         # ตัวที่แยกสองอย่างนี้ออกจากกันคือแนวการเคลื่อนที่ ไม่ใช่ความถี่
SRC_T_NAT = 0.35         # ดัชนีต่ำกว่านี้ = สรุปว่าธรรมชาติ
SRC_T_HUM = 0.65         # ดัชนีสูงกว่านี้ = สรุปว่ากิจกรรมมนุษย์
SRC_FLOOR = 0.002        # mm/s — เบากว่านี้ถือว่าเงียบ ผลการแยกแยะเชื่อถือไม่ได้
SRC_BUCKET_MIN = 15.0    # หนึ่งแท่งบนหน้า HISTORY กว้างกี่นาที
HISTORY_AXIS_LINES = True  # วาดเส้นค่าพีครายแกนทับแท่งด้วยไหม (False = เหลือแต่แท่ง อ่านง่ายขึ้น)
SRC_COL_NAT = (72, 198, 188)    # สีแทนส่วนที่มาจากธรรมชาติ
SRC_COL_HUM = (255, 168, 64)    # สีแทนส่วนที่มาจากกิจกรรมมนุษย์
SRC_COL_MIX = (198, 206, 220)   # สีตอนแยกไม่ชัด

# ---- หน้า LIVE ----
WAVE_SPAN = 120.0        # หน้า wave แสดงย้อนหลังกี่วินาที
QUANTITY = "velocity"    # สิ่งที่หน้า LIVE แสดง: "velocity" / "acceleration" / "displacement"
#   velocity     -> um/s     (geophone วัดมาตรงตัว)
#   acceleration -> um/s^2   (หาอนุพันธ์ของความเร็ว)
#   displacement -> um       (อินทิเกรตความเร็ว แล้วตัดการดริฟต์ทิ้ง)

# ---- ชดเชยการตอบสนองของ geophone ----
# geophone ไม่ได้วัดความเร็วตรง ๆ ทุกความถี่ ต่ำกว่า f0 มันตอบสนองลดลงเป็น f^2
# ตัวกรองนี้ "ย้ายมุมตัด" จาก f0 ลงมาที่ GEO_FTARGET ค่าที่อ่านได้จึงถูกต้องลงไปถึงตรงนั้น
GEO_CORRECT = True       # False = ปิดการชดเชย (ได้ค่าดิบเหมือนเดิม)
GEO_F0 = C.GEO_F0        # ความถี่ธรรมชาติของเซ็นเซอร์ (Hz) — ตามฉลากคือ 4.5
GEO_ZETA = 0.30          # damping จริงของขดลวด **ตอนยังไม่ใส่ shunt resistor**
                         # ถ้าใส่ shunt แล้วให้เปลี่ยนเป็นค่าตามที่คำนวณ (ปกติ 0.6-0.7)
GEO_FTARGET = 1.0        # ขยายการตอบสนองลงมาถึงกี่ Hz (ยิ่งต่ำยิ่งขยาย noise มาก)
GEO_ZETA_T = 0.707       # damping ของมุมตัดใหม่ 0.707 = แบนที่สุดไม่มียอดโด่ง
GEO_SETTLE = 3.0         # หลังสร้างตัวกรองใหม่ กลบค่าไว้กี่วินาทีรอให้นิ่ง

# ---- แถบบอกสเปกเซนเซอร์บนหน้า LIVE ----
# ค่าพวกนี้เป็นคุณสมบัติของตัวเซนเซอร์ ไม่ใช่ค่าที่วัดได้ จึงแสดงเป็นข้อความคงที่
LIVE_SPEC = True         # False = ซ่อนแถบนี้ คืนพื้นที่ให้กราฟ
SPEC_H = 16              # ความสูงของแถบ (px)


def spec_text():
    """บรรทัดบอกสเปกเซนเซอร์ — อ่านจาก config เพื่อไม่ให้ตัวเลขสองที่ไม่ตรงกัน"""
    f0, ft = C.GEO_F0, getattr(C, "GEO_F0_TOL", 0.0)
    sv, st_ = C.GEO_SENS, getattr(C, "GEO_SENS_TOL", 0.0)
    fpart = f"{f0:g} Hz" + (f" \u00b1{ft:g} Hz" if ft else "")
    spart = f"{sv:g} V/m/s" + (f" \u00b1{st_*100:g}%" if st_ else "")
    return (L(f"เซนเซอร์ {fpart}   ความไว {spart}",
              f"sensor {fpart}   sensitivity {spart}"))


def draw_spec(d, W, y, f_sm):
    """วาดแถบสเปกใต้หัวจอ คืนความสูงที่ใช้ไป"""
    if not LIVE_SPEC:
        return 0
    d.rectangle([0, y, W - 1, y + SPEC_H - 2], fill=(20, 24, 32))
    txt = spec_text()
    tw = d.textlength(txt, font=f_sm)
    d.text(((W - tw) / 2, y + 1), txt, font=f_sm, fill=(140, 152, 175))
    return SPEC_H

# ---- เตือนแผ่นดินไหว ----
# เกณฑ์เทียบจากตาราง PGV -> ความรุนแรง MMI ของ USGS ShakeMap
#   11-34 mm/s = MMI IV  รู้สึกได้ทั้งอาคาร ของแขวนแกว่ง
#   34-81 mm/s = MMI V   ทุกคนรู้สึก ของตกแตก
#   81-160     = MMI VI  เริ่มเสียหายเล็กน้อย
# ***สำคัญ*** เพดานที่ฮาร์ดแวร์ชุดนี้วัดได้ขึ้นกับ ADS_GAIN ใน config.py
# โปรแกรมจะคำนวณและเตือนให้ตอนเริ่มทำงาน ถ้าตั้งเกณฑ์ไว้เกินเพดาน
QUAKE_ENABLE = True
# เกณฑ์อิง "ระดับความรุนแรง" (Instrumental Intensity) ของ USGS ShakeMap
# ไม่ได้อิงขนาดแผ่นดินไหว (ริกเตอร์) เพราะสถานีเดียววัดขนาดไม่ได้
# ขนาดต้องรู้ระยะห่างจากศูนย์กลางด้วย ส่วนความรุนแรงคือสิ่งที่วัดได้ ณ จุดติดตั้ง
MMI_LEVELS = [("I", "ไม่รู้สึก", 0.0),        # ขอบล่างของแต่ละระดับ (mm/s)
              ("II", "รู้สึกเบามาก", 0.215),
              ("III", "รู้สึกได้เล็กน้อย", 1.35),
              ("IV", "รู้สึกได้ปานกลาง", 14.1),
              ("V", "แรง", 46.5),
              ("VI", "แรงมาก", 96.4),
              ("VII", "รุนแรง", 200.0)]


def mmi_of(mm):
    """ระดับความรุนแรงจากความเร็วอนุภาคสูงสุด คืน (เลขโรมัน, คำบรรยาย)"""
    out = MMI_LEVELS[0][:2]
    for roman, word, lo in MMI_LEVELS:
        if mm >= lo:
            out = (roman, word)
    return out


QUAKE_WARN = 1.35        # mm/s  ระดับ III "รู้สึกได้เล็กน้อย" = ขึ้นแถบเหลืองเตือน
QUAKE_DANGER = 14.1      # mm/s  ระดับ IV "รู้สึกได้ปานกลาง" = จอแดงเต็มจอ
QUAKE_WIN = 1.0          # ใช้ข้อมูลกี่วินาทีล่าสุดมาตัดสิน
QUAKE_ON_SEC = 1.0       # ต้องแรงต่อเนื่องกี่วินาทีถึงจะประกาศ (กันเคาะโต๊ะ/เดินผ่าน)
QUAKE_OFF = 0.4          # เลิกเตือนเมื่อค่าลดลงเหลือกี่เท่าของเกณฑ์
QUAKE_HOLD = 20.0        # ค้างจอแดงไว้อย่างน้อยกี่วินาทีหลังสงบ

# ---- ไม่เตือนถ้าการสั่นมาจากกิจกรรมมนุษย์ ----
# คนเดิน ประตูกระแทก รถวิ่งผ่าน ทำให้พื้นสั่นถึงเกณฑ์ระดับ III ได้ง่ายมาก
# ถ้าปล่อยไว้ แถบเหลืองจะขึ้นทั้งวันจนไม่มีใครสนใจ
#
# แต่ตัวแยกแหล่งกำเนิดเป็นแค่การประมาณจากย่านความถี่กับแนวการสั่น ไม่ใช่การยืนยัน
# จึงยอมให้มันปิดได้เฉพาะ "แถบเหลืองเตือน" เท่านั้น
# ระดับอันตราย (จอแดง) จะขึ้นเสมอไม่ว่าจะตัดสินว่ามาจากอะไร
# เพราะพลาดแผ่นดินไหวจริงเสียหายกว่าการเตือนผิดมาก
QUAKE_SKIP_HUMAN = True
QUAKE_CLIP_SEC = 2.0     # สัญญาณดิบชนเต็มสเกลภายในกี่วินาที ถือว่ายังชนอยู่
QUAKE_LOG = os.path.join(C.DATA_DIR, "quake.csv")

# เพดานที่วัดได้จริงก่อนสัญญาณดิบชนเต็มสเกล ADC (mm/s)
ADC_FSR_V = C.ADS_VREF / C.ADS_GAIN
CLIP_MMS = 0.95 * ADC_FSR_V / C.GEO_SENS * 1000.0

# ข้อมูลภายในเป็น mm/s เสมอ ค่าพวกนี้ใช้แปลงตอนแสดงผลอย่างเดียว
MM_TO_U = 1.0                        # หน่วยหลักคือ mm/s อยู่แล้ว ไม่ต้องแปลง
UNIT_OF = {"velocity": ("mm/s", "mm/s"),
           "acceleration": ("\u00b5m/s\u00b2", "um/s2"),
           "displacement": ("\u00b5m", "um")}
VEL_UNIT = ("mm/s", "mm/s")          # หน่วยของ PVS และหน้า HISTORY/SUMMARY
VLAB = "um/s"                        # ตั้งค่าจริงตอนเริ่มโปรแกรม


# ======================================================================
class Biquad:
    """ตัวกรอง IIR สองขั้ว-สองศูนย์ ทำงานทีละตัวอย่าง (Direct Form II transposed)

    ทำงานแบบไหลต่อเนื่อง จำสถานะข้ามเฟรมได้ จึงไม่มีรอยต่อที่ขอบบล็อก
    แบบที่การชดเชยด้วย FFT ทีละก้อนจะมี
    """

    __slots__ = ("b0", "b1", "b2", "a1", "a2", "z1", "z2")

    def __init__(self, b, a):
        self.b0, self.b1, self.b2 = b
        self.a1, self.a2 = a[1], a[2]
        self.z1 = self.z2 = 0.0

    def step(self, x):
        y = self.b0 * x + self.z1
        self.z1 = self.b1 * x - self.a1 * y + self.z2
        self.z2 = self.b2 * x - self.a2 * y
        return y


def geophone_biquad(fs, f0, zeta, f_target, zeta_t):
    """ออกแบบตัวกรองชดเชย geophone ด้วยวิธี bilinear transform

    เซ็นเซอร์มีการตอบสนอง  H(s) = s^2 / (s^2 + 2*zeta*w0*s + w0^2)
    ถ้าจะแก้ให้ตรงเป๊ะต้องคูณด้วย 1/H(s) ซึ่งมีขั้วซ้อนที่ s=0
    -> อัตราขยายที่ความถี่ต่ำพุ่งเป็นอนันต์ สัญญาณจะดริฟต์หนีทันที

    จึงไม่ยกเลิกทิ้งทั้งหมด แต่ "ย้ายมุมตัด" จาก f0 ลงไปที่ f_target แทน

        G(s) = (s^2 + 2*zeta *w0*s + w0^2)      <- ยกเลิกของเซ็นเซอร์
               ---------------------------
               (s^2 + 2*zeta_t*wt*s + wt^2)     <- ใส่มุมตัดใหม่ที่ต่ำกว่า

    อัตราขยายสูงสุดจึงถูกจำกัดไว้ที่ (f0/f_target)^2 โดยธรรมชาติของสูตรเอง
    ไม่ต้องไปตัดยอดทีหลังให้เฟสเพี้ยน
    """
    K = 2.0 * fs                      # bilinear: s -> K(1-z^-1)/(1+z^-1)
    ws = 2.0 * np.pi * f0
    wt = 2.0 * np.pi * f_target
    a1, a0 = 2.0 * zeta * ws, ws * ws         # สัมประสิทธิ์ตัวเศษ (ฝั่งเซ็นเซอร์)
    b1, b0 = 2.0 * zeta_t * wt, wt * wt       # สัมประสิทธิ์ตัวส่วน (มุมตัดใหม่)
    KK = K * K
    n = [KK + a1 * K + a0, 2.0 * (a0 - KK), KK - a1 * K + a0]
    d = [KK + b1 * K + b0, 2.0 * (b0 - KK), KK - b1 * K + b0]
    return [x / d[0] for x in n], [1.0, d[1] / d[0], d[2] / d[0]]


# ======================================================================
class Sampler(threading.Thread):
    """อ่าน ADC ต่อเนื่อง + ตรวจว่าแกนไหนมีเซ็นเซอร์ต่ออยู่"""

    def __init__(self):
        super().__init__(daemon=True)
        self.buf = {n: deque([0.0] * N, maxlen=N) for n in NAMES}
        self.ok = {n: False for n in NAMES}
        self.lock = threading.Lock()
        self.fs = 0.0
        self.err = None
        self.adc = None
        self.filt = {}                 # ตัวกรองชดเชย geophone แยกตามแกน
        self.filt_fs = 0.0             # fs ที่ใช้ออกแบบตัวกรองชุดปัจจุบัน
        self.settle_until = 0.0        # กลบค่าไว้จนถึงเวลานี้ (รอตัวกรองนิ่ง)
        self.clip_t = 0.0              # เวลาล่าสุดที่สัญญาณ *ดิบ* ชนเต็มสเกล ADC

    def clipping(self):
        """สัญญาณดิบชนเพดาน ADC อยู่ไหม — แปลว่าของจริงแรงกว่าที่อ่านได้"""
        return (time.time() - self.clip_t) < QUAKE_CLIP_SEC

    def _sync_filters(self):
        """สร้าง/สร้างใหม่ตัวกรองชดเชยเมื่ออัตราสุ่มเปลี่ยนไปมาก

        ตัวกรองขึ้นกับ fs ซึ่งวัดได้จริงตอนรันเท่านั้น (เปลี่ยนตามจำนวนแกนที่ต่ออยู่)
        จึงต้องรอวัด fs ก่อนแล้วค่อยสร้าง
        """
        if not GEO_CORRECT:
            return
        fs = self.fs
        if fs < 8.0 * GEO_F0:          # ช้าเกินไป ตัวกรองจะเพี้ยน ปล่อยค่าดิบดีกว่า
            return
        if self.filt and abs(fs - self.filt_fs) < 0.10 * self.filt_fs:
            return                     # เปลี่ยนไม่ถึง 10% ใช้ของเดิมต่อ ไม่ต้องรีเซ็ต
        b, a = geophone_biquad(fs, GEO_F0, GEO_ZETA, GEO_FTARGET, GEO_ZETA_T)
        self.filt = {n: Biquad(b, a) for n in NAMES}
        self.filt_fs = fs
        self.settle_until = time.time() + GEO_SETTLE
        print(f"ชดเชย geophone: {GEO_F0:.1f} Hz -> {GEO_FTARGET:.1f} Hz  "
              f"(zeta {GEO_ZETA} -> {GEO_ZETA_T}, ขยายต่ำสุดไม่เกิน "
              f"{(GEO_F0/GEO_FTARGET)**2:.1f} เท่า, fs {fs:.1f} Hz)", flush=True)

    def _measure(self):
        self.adc.configure(gain=C.ADS_GAIN, rate=C.ADS_RATE,
                           filt=C.ADS_FILTER, one_shot=True)
        self.adc.self_offset_cal()

    def detect(self):
        """คู่ที่มีขดลวดเชื่อมอยู่ -> ค่ากลางเล็กมากและวัดซ้ำได้ค่าเดิม"""
        self.adc.configure(gain=1, rate=400, filt="sinc4", one_shot=True)
        for n, p, q in AXES:
            a = statistics.fmean([self.adc.convert(p, q)[0] for _ in range(25)])
            b = statistics.fmean([self.adc.convert(p, q)[0] for _ in range(25)])
            self.ok[n] = abs(a) < 5e-3 and abs(b) < 5e-3 and abs(a - b) < 1e-3
        self._measure()

    def run(self):
        while True:
            try:
                if self.adc is None:
                    self.adc = ADS1263(bus=C.ADS_BUS, dev=C.ADS_DEV,
                                       speed_hz=C.ADS_SPI_HZ,
                                       pin_reset=C.ADS_PIN_RESET,
                                       pin_start=C.ADS_PIN_START,
                                       pin_drdy=C.ADS_PIN_DRDY, vref=C.ADS_VREF)
                    self.adc.reset()
                    self._measure()
                    self.err = None

                self.detect()
                live = [(n, p, q) for n, p, q in AXES if self.ok[n]]
                if not live:
                    time.sleep(2)
                    continue

                cnt, t0 = 0, time.perf_counter()
                while time.perf_counter() - t0 < RESCAN or all(self.ok.values()):
                    vals = []
                    for n, p, q in live:
                        v = self.adc.convert(p, q)[0] / C.GEO_SENS * 1000.0
                        if abs(v) >= CLIP_MMS:     # เช็คก่อนกรอง เพราะตัวกรองขยายค่าได้
                            self.clip_t = time.time()
                        f = self.filt.get(n)
                        if f is not None:
                            v = f.step(v)          # ชดเชยตั้งแต่ต้นทาง
                        vals.append((n, v))
                    if time.time() < self.settle_until:
                        vals = [(n, 0.0) for n, _ in vals]   # กลบทรานเซียนต์ตอนตัวกรองเริ่มทำงาน
                    with self.lock:
                        for n, v in vals:
                            self.buf[n].append(v)
                    cnt += 1
                    if cnt % 40 == 0:
                        self.fs = cnt / (time.perf_counter() - t0)
                        self._sync_filters()
            except Exception as e:
                self.err = f"{type(e).__name__}: {e}"
                traceback.print_exc()
                try:
                    self.adc.close()
                except Exception:
                    pass
                self.adc = None
                self.filt = {}                     # ต่อใหม่ = สถานะตัวกรองใช้ไม่ได้แล้ว
                self.filt_fs = 0.0
                time.sleep(2)

    def snap(self):
        with self.lock:
            return ({n: np.fromiter(self.buf[n], float) for n in NAMES}, dict(self.ok))


# ======================================================================
class History:
    """สถิติรายนาที เก็บในหน่วยความจำ + ต่อท้ายไฟล์ CSV"""

    # nat/hum = ค่า RMS ของแต่ละย่านความถี่ในนาทีนั้น (mm/s)
    # เก็บลงไฟล์ด้วย เพื่อให้ย้อนดูการแยกแหล่งกำเนิดของช่วงที่ผ่านมาได้
    COLS = (["epoch"]
            + [f"{n}_{k}" for n in NAMES for k in ("rms", "pk", "dom", "nat", "hum")]
            + ["pvs"])

    def __init__(self):
        self.rows = deque(maxlen=HIST_MAX)
        self.acc = self._blank()
        self.t_next = time.time() + LOG_PERIOD
        self.load()

    @staticmethod
    def _blank():
        return {"pk": {n: 0.0 for n in NAMES}, "rms": {n: 0.0 for n in NAMES},
                "dom": {n: 0.0 for n in NAMES},
                "nat": {n: 0.0 for n in NAMES}, "hum": {n: 0.0 for n in NAMES},
                "pvs": 0.0, "cnt": 0}

    def load(self):
        """อ่านประวัติเดิม — ข้ามแถวที่เสียทีละแถว ไม่ทิ้งทั้งไฟล์

        ไฟฟ้าดับตอนกำลังเขียนจะทิ้ง 'รู' เป็นไบต์ศูนย์ (\\x00) ไว้กลางไฟล์
        แถวรอบ ๆ รูยังใช้ได้ จึงต้องล้างไบต์ศูนย์แล้วอ่านต่อ ไม่ใช่ยอมแพ้ทั้งไฟล์
        """
        if not os.path.exists(HIST_FILE):
            return
        good = bad = 0
        hdr = None
        try:
            with open(HIST_FILE, newline="", errors="replace") as f:
                clean = (ln.replace("\x00", "") for ln in f)
                rd = csv.DictReader(clean)
                for r in rd:
                    try:
                        row = {k: float(r.get(k) or 0.0) for k in self.COLS}
                    except (TypeError, ValueError):
                        bad += 1
                        continue
                    if not (1e9 < row["epoch"] < 4e9):   # เวลาต้องสมเหตุสมผล
                        bad += 1
                        continue
                    self.rows.append(row)
                    good += 1
                hdr = rd.fieldnames
        except Exception as e:
            print("อ่านประวัติไม่ได้:", e, flush=True)

        if self.rows:                                    # เรียงเวลาใหม่ เผื่อไฟล์สลับลำดับ
            ordered = sorted(self.rows, key=lambda r: r["epoch"])
            self.rows.clear()
            self.rows.extend(ordered)
        msg = f"โหลดประวัติ {good} แถว"
        if bad:
            msg += f"  (ข้ามแถวเสีย {bad} แถว — น่าจะโดนไฟดับตอนเขียน)"
        print(msg, flush=True)

        # ไฟล์ที่เขียนไว้ก่อนเพิ่มคอลัมน์ nat/hum จะมีหัวตารางไม่ครบ
        # ถ้าต่อท้ายเลยค่าจะเข้าผิดช่อง จึงต้องเขียนไฟล์ใหม่ทั้งก้อนก่อน
        if hdr and [h.strip() for h in hdr if h] != list(self.COLS):
            self._migrate()

    def _migrate(self):
        """เขียนไฟล์ประวัติใหม่ด้วยหัวตารางชุดปัจจุบัน แถวเดิมที่ขาดคอลัมน์เติม 0"""
        tmp = HIST_FILE + ".tmp"
        try:
            with open(tmp, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=self.COLS)
                w.writeheader()
                for r in self.rows:
                    w.writerow({k: f"{r.get(k, 0.0):.6f}" for k in self.COLS})
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, HIST_FILE)       # สลับไฟล์ทีเดียว ไฟดับกลางทางก็ไม่เสียของเดิม
            print(f"ปรับโครงสร้างไฟล์ประวัติให้มีคอลัมน์ย่านความถี่ "
                  f"({len(self.rows)} แถว — แถวเก่าจะไม่มีข้อมูลแยกแหล่งกำเนิด)",
                  flush=True)
        except Exception as e:
            print("ปรับโครงสร้างไฟล์ประวัติไม่ได้:", e, flush=True)
            try:
                os.remove(tmp)
            except OSError:
                pass

    def feed(self, stats, pvs):
        """เรียกทุกเฟรม — เก็บค่าสูงสุดของช่วงนาทีนี้"""
        a = self.acc
        for n in NAMES:
            a["pk"][n] = max(a["pk"][n], stats[n]["pk"])
            a["rms"][n] += stats[n]["rms"]
            if stats[n]["pk"] >= a["pk"][n]:
                a["dom"][n] = stats[n]["dom"]
            # พลังงานบวกกันแบบกำลังสอง แล้วถอดรากตอน flush จึงได้ RMS ของนาทีนั้น
            a["nat"][n] += stats[n].get("nat", 0.0) ** 2
            a["hum"][n] += stats[n].get("hum", 0.0) ** 2
        a["pvs"] = max(a["pvs"], pvs)
        a["cnt"] += 1

        if time.time() >= self.t_next:
            self.flush()

    def flush(self):
        a = self.acc
        c = max(a["cnt"], 1)
        row = {"epoch": time.time(), "pvs": a["pvs"]}
        for n in NAMES:
            row[f"{n}_rms"] = a["rms"][n] / c
            row[f"{n}_pk"] = a["pk"][n]
            row[f"{n}_dom"] = a["dom"][n]
            row[f"{n}_nat"] = (a["nat"][n] / c) ** 0.5
            row[f"{n}_hum"] = (a["hum"][n] / c) ** 0.5
        self.rows.append(row)
        self.acc = self._blank()
        self.t_next = time.time() + LOG_PERIOD
        try:
            os.makedirs(C.DATA_DIR, exist_ok=True)
            new = not os.path.exists(HIST_FILE)
            with open(HIST_FILE, "a", newline="") as f:
                w = csv.DictWriter(f, fieldnames=self.COLS)
                if new:
                    w.writeheader()
                w.writerow({k: f"{row[k]:.6f}" for k in self.COLS})
                f.flush()
                os.fsync(f.fileno())     # เขียนลงการ์ดจริง ไม่ค้างใน cache รอไฟดับ
        except Exception as e:
            print("เขียนประวัติไม่ได้:", e, flush=True)

    def window(self, hours):
        cut = time.time() - hours * 3600
        return [r for r in self.rows if r["epoch"] >= cut]

    def stat(self, hours, name, key="pk"):
        w = self.window(hours)
        vals = [r[f"{name}_{key}"] for r in w] or [0.0]
        return max(vals), sum(vals) / len(vals)


def pick_label(font, pair):
    """เลือกป้ายหน่วย ถ้าฟอนต์ไม่รองรับ µ หรือ ² ให้ใช้ตัวสำรอง ASCII"""
    nice, plain = pair
    try:
        for ch in set(nice) - set(plain):
            if font.getmask(ch).getbbox() is None:
                return plain
        return nice
    except Exception:
        return plain


def fmt_v(mm):
    """จัดรูปแบบความเร็วเป็น mm/s โดยเลือกจำนวนทศนิยมตามขนาดของค่า

    mm/s เป็นหน่วยมาตรฐานของการวัดแรงสั่นสะเทือน (DIN 4150, BS 7385)
    แต่ช่วงที่เครื่องนี้วัดกว้างมาก ตั้งแต่ 0.002 ถึง 20 กว่า
    ถ้าตรึงทศนิยมไว้ค่าเดียว ค่าน้อยจะกลายเป็น 0.00 ส่วนค่ามากจะรกเกินจำเป็น
    """
    a = abs(mm)
    if a < 1.0:
        return f"{mm:.3f}"
    if a < 10.0:
        return f"{mm:.2f}"
    return f"{mm:,.1f}"


def fmt_tick(v):
    """ตัวเลขขีดสเกลแบบสั้น: 0 / 1.5 / 1200 / 5e-4 / 2e5"""
    if v == 0:
        return "0"
    a = abs(v)
    if 1e-2 <= a < 1e4:
        return f"{v:.4g}"
    ex = int(np.floor(np.log10(a)))
    m = v / 10 ** ex
    ms = f"{m:.0f}" if abs(m - round(m)) < 0.05 else f"{m:.1f}"
    return f"{ms}e{ex}"


def transform(v, fs):
    """แปลงความเร็ว (mm/s) เป็นปริมาณที่เลือก แล้วคืนค่าในหน่วยไมโคร"""
    if QUANTITY == "acceleration":
        a = np.diff(v) * fs
        return np.concatenate(([a[0] if len(a) else 0.0], a)) * MM_TO_U
    if QUANTITY == "displacement":
        x = np.cumsum(v) / max(fs, 1.0)
        t = np.arange(len(x), dtype=float)
        A = np.vstack([t, np.ones_like(t)]).T
        coef, *_ = np.linalg.lstsq(A, x, rcond=None)
        return (x - A @ coef) * MM_TO_U          # ตัดการดริฟต์เชิงเส้นจากการอินทิเกรต
    return v * MM_TO_U










class WaveTrace:
    """เก็บช่วงต่ำสุด-สูงสุดของแต่ละคอลัมน์เวลา ค่าใหม่เข้าทางขวา"""

    BIG = 1e30

    def __init__(self, w, span):
        self.w = w
        self.lo = np.zeros(w, dtype=np.float32)
        self.hi = np.zeros(w, dtype=np.float32)
        self.dt = span / w
        self.t_next = time.time()
        self.acc_lo, self.acc_hi = self.BIG, -self.BIG
        self.filled = 0
        self.scale = 1e-4

    def feed(self, seg):
        if len(seg):
            self.acc_lo = min(self.acc_lo, float(seg.min()))
            self.acc_hi = max(self.acc_hi, float(seg.max()))
        now = time.time()
        if now < self.t_next or self.acc_hi < -self.BIG / 2:
            return
        n = min(int((now - self.t_next) / self.dt) + 1, self.w)
        self.t_next = now + self.dt
        lo, hi = self.acc_lo, self.acc_hi
        self.acc_lo, self.acc_hi = self.BIG, -self.BIG
        if n >= self.w:
            self.lo[:], self.hi[:] = lo, hi
        else:
            self.lo[:-n], self.hi[:-n] = self.lo[n:], self.hi[n:]
            self.lo[-n:], self.hi[-n:] = lo, hi
        self.filled = min(self.filled + n, self.w)
        if self.filled:
            k = self.w - self.filled
            top = max(float(np.abs(self.hi[k:]).max()),
                      float(np.abs(self.lo[k:]).max()), 1e-9)
            self.scale = max(top, self.scale * 0.98)


def nice_step(maxval, want=2):
    """ระยะขีดสเกลเป็นเลขกลม ๆ ให้มีราว want ขีดต่อครึ่งบน"""
    if maxval <= 0:
        return 1.0
    raw = maxval / want
    p = 10 ** np.floor(np.log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        if raw <= m * p:
            return float(m * p)
    return float(10 * p)


def vtext(d_unused, txt, font, fill):
    """ข้อความตะแคง 90 องศา"""
    tmp = Image.new("RGB", (int(ImageDraw.Draw(Image.new("RGB", (1, 1)))
                                .textlength(txt, font=font)) + 4, 16), (8, 10, 14))
    ImageDraw.Draw(tmp).text((2, 0), txt, font=font, fill=fill)
    return tmp.rotate(90, expand=True)


# ======================================================================
_HANN = {}


def hann(n):
    """หน้าต่าง Hann แบบใช้ซ้ำ — สร้างครั้งเดียวต่อขนาด ไม่ต้องสร้างใหม่ทุกเฟรม"""
    w = _HANN.get(n)
    if w is None:
        w = _HANN[n] = np.hanning(n)
    return w


def spectrum(v, fs):
    win = hann(len(v))
    sp = np.abs(np.fft.rfft((v - v.mean()) * win)) * 2 / np.sum(win)
    sp[0] = 0.0
    return sp


# ตัวแก้พลังงานของหน้าต่าง (noise power bandwidth)
#
# spectrum() ปรับสเกลไว้ให้ "ยอดของช่องที่ตรงความถี่พอดี" เท่ากับแอมพลิจูดจริง
# แต่หน้าต่าง Hann ทำให้คลื่นลูกเดียวกระจายออกไปอีกข้างละช่อง (1 : 0.5 : 0.5)
# ถ้าเอาทุกช่องในย่านมาบวกกำลังสอง จะได้พลังงานเกินจริง 1.5 เท่า
# ตัวคูณนี้ดึงกลับให้ตรง — ได้มาจากทฤษฎีบทพาร์เซอวาล  (Hann -> 2/3 พอดี)
WIN_PWR = float(np.sum(hann(N)) ** 2 / (N * np.sum(hann(N) ** 2)))


def band_rms(sp, freq, lo, hi):
    """ค่า RMS ของสัญญาณเฉพาะในย่าน lo..hi Hz (หน่วยเดียวกับสัญญาณต้นทาง)

    sp ที่ spectrum() คืนมาเป็น "แอมพลิจูดยอด" ของไซน์แต่ละช่อง
    ไซน์ยอด A มีค่า RMS = A/sqrt(2) พลังงานรวมของย่านจึงเป็น sum(A^2/2)
    แล้วคูณ WIN_PWR แก้การกระจายพลังงานของหน้าต่าง Hann (ดูคำอธิบายที่ WIN_PWR)
    """
    if sp is None or len(freq) == 0:
        return 0.0
    m = (freq >= lo) & (freq < hi)
    if not m.any():
        return 0.0
    k = min(len(sp), len(m))
    return float(np.sqrt(np.sum(sp[:k][m[:k]] ** 2) / 2.0 * WIN_PWR))


def analyse(data, ok, fs):
    """คืนสถิติปัจจุบันของทุกแกน + PVS"""
    out, freq = {}, np.fft.rfftfreq(N, 1 / max(fs, 1.0))
    nyq = max(fs, 1.0) / 2.0
    # ย่านบนถูกจำกัดด้วย Nyquist เสมอ ถ้าต่อเซ็นเซอร์น้อยแกน fs จะสูงขึ้น ย่านก็กว้างขึ้นเอง
    nat_lo, nat_hi = SRC_NAT[0], min(SRC_NAT[1], nyq * 0.95)
    hum_lo, hum_hi = min(SRC_HUM[0], nat_hi), min(SRC_HUM[1], nyq * 0.95)
    for n in NAMES:
        if not ok[n]:
            out[n] = {"rms": 0.0, "pk": 0.0, "dom": 0.0, "sp": None,
                      "nat": 0.0, "hum": 0.0}
            continue
        v = data[n] - data[n].mean()
        sp = spectrum(data[n], fs)
        k = int(np.argmax(sp))
        out[n] = {"rms": float(np.sqrt(np.mean(v ** 2))), "pk": float(np.max(np.abs(v))),
                  "dom": float(freq[k]) if k < len(freq) else 0.0, "sp": sp,
                  "nat": band_rms(sp, freq, nat_lo, nat_hi) if SRC_ENABLE else 0.0,
                  "hum": band_rms(sp, freq, hum_lo, hum_hi) if SRC_ENABLE else 0.0}
    live = [n for n in NAMES if ok[n]]
    pvs = 0.0
    if live:
        st = np.vstack([data[n] - data[n].mean() for n in live])
        pvs = float(np.max(np.sqrt(np.sum(st ** 2, axis=0))))
    return out, pvs


# ======================================================================
# เตือนแผ่นดินไหว
# ======================================================================
def quake_level(data, ok, fs):
    """ความแรงรวมสามแกนของช่วง QUAKE_WIN วินาทีล่าสุด (mm/s)

    ใช้ช่วงสั้นแทนบัฟเฟอร์ทั้งก้อน เพราะบัฟเฟอร์ยาว 5 วินาที
    ค่าพีคจากการเคาะโต๊ะครั้งเดียวจะค้างอยู่ในนั้นนานเกินกว่าจะแยกออกจากของจริง
    """
    live = [n for n in NAMES if ok[n]]
    if not live or fs < 1.0:
        return 0.0
    k = max(8, min(N, int(fs * QUAKE_WIN)))
    m = np.vstack([data[n][-k:] - data[n][-k:].mean() for n in live])
    return float(np.max(np.sqrt(np.sum(m ** 2, axis=0))))


class Quake:
    """ตัดสินว่าเข้าข่ายแผ่นดินไหวหรือยัง

    มีสามอย่างที่กันจอกะพริบเข้า-ออก
      1. ต้องแรงต่อเนื่อง QUAKE_ON_SEC วินาที ถึงจะประกาศ
      2. เลิกเตือนที่ระดับต่ำกว่าตอนเริ่มเตือน (hysteresis)
      3. ค้างจออีก QUAKE_HOLD วินาทีหลังสงบแล้ว
    """

    def __init__(self):
        self.level = 0        # 0 ปกติ, 1 เตือน, 2 อันตราย
        self.since = 0.0      # เริ่มเกินเกณฑ์เมื่อไร (0 = ยังไม่เกิน)
        self.t_on = 0.0       # ประกาศเตือนเมื่อไร
        self.until = 0.0      # ค้างจอไว้อย่างน้อยถึงเวลานี้
        self.t_act = 0.0      # ครั้งสุดท้ายที่ยังสั่นแรงอยู่จริง (ไม่นับช่วงค้างจอ)
        self.peak = 0.0       # ค่าสูงสุดของเหตุการณ์นี้
        self.clipped = False  # เคยชนเพดาน ADC ระหว่างเหตุการณ์นี้ไหม
        self.last = None      # เหตุการณ์ที่เพิ่งจบ (t_on, t_off, peak, clipped)
        self.muted = False    # รอบนี้ถูกกดไว้เพราะตัดสินว่ามาจากกิจกรรมมนุษย์

    def update(self, v, clipped, now, human=False):
        want = 2 if (clipped or v >= QUAKE_DANGER) else (1 if v >= QUAKE_WARN else 0)
        if want == 1 and human and QUAKE_SKIP_HUMAN:
            want = 0                    # กดเฉพาะแถบเหลือง จอแดงไม่เคยถูกกด
            self.muted = True
        else:
            self.muted = False

        if want > self.level:                       # จะยกระดับ ต้องแรงต่อเนื่องก่อน
            if self.since == 0.0:
                self.since = now
            if now - self.since >= QUAKE_ON_SEC:
                if self.level == 0:
                    self.t_on, self.peak, self.t_act = now, v, now
                self.level = want
                self.until = now + QUAKE_HOLD
                self.since = 0.0
        else:
            self.since = 0.0

        if self.level:
            self.peak = max(self.peak, v)
            self.clipped = self.clipped or clipped
            thr = QUAKE_DANGER if self.level == 2 else QUAKE_WARN
            if v < thr * QUAKE_OFF and not clipped:
                if now >= self.until:
                    self.level = want               # ลดระดับตามค่าปัจจุบัน
                    if self.level == 0:
                        # เก็บสรุปเหตุการณ์ไว้ก่อนล้างค่า ไม่งั้นตอนบันทึกจะได้ 0
                        self.last = (self.t_on, self.t_act, self.peak, self.clipped)
                        self.clipped = False
                        self.peak = 0.0
            else:
                self.t_act = now                    # ยังสั่นแรงอยู่
                self.until = max(self.until, now + QUAKE_HOLD)
        return self.level

    def log(self):
        """บันทึกเหตุการณ์ที่เพิ่งจบลงไฟล์"""
        if not self.last:
            return
        t_on, t_off, peak, clipped = self.last
        try:
            os.makedirs(C.DATA_DIR, exist_ok=True)
            new = not os.path.exists(QUAKE_LOG)
            with open(QUAKE_LOG, "a", newline="") as f:
                w = csv.writer(f)
                if new:
                    w.writerow(["start", "end", "dur_s", "peak_um_s", "over_range"])
                w.writerow([datetime.fromtimestamp(t_on).isoformat(timespec="seconds"),
                            datetime.fromtimestamp(t_off).isoformat(timespec="seconds"),
                            f"{t_off - t_on:.1f}", f"{fmt_v(peak)}",
                            int(clipped)])
                f.flush()
                os.fsync(f.fileno())
        except Exception as e:
            print("เขียน quake.csv ไม่ได้:", e, flush=True)


_FONTS = {}


def big_font(size):
    f = _FONTS.get(size)
    if f is None:
        f = _FONTS[size] = load_font(size)
    return f


def ctext(d, W, y, txt, font, fill):
    d.text(((W - d.textlength(txt, font=font)) / 2, y), txt, font=font, fill=fill)


def page_quake(d, W, H, q, v, now, thai):
    """จอแดงเต็มจอตอนสั่นแรงถึงขั้นอันตราย"""
    flash = int(now * 2) % 2
    d.rectangle([0, 0, W, H], fill=(196, 22, 22) if flash else (146, 12, 12))
    d.rectangle([0, 0, W - 1, H - 1], outline=(255, 235, 120), width=3)

    f_hero, f_mid, f_sm = big_font(46), big_font(20), big_font(14)
    ctext(d, W, 26, "แผ่นดินไหว" if thai else "EARTHQUAKE", f_hero, (255, 255, 255))
    ctext(d, W, 92, "อันตราย — หมอบ ป้อง เกาะ  อยู่ห่างหน้าต่าง" if thai
          else "DANGER - DROP, COVER, HOLD ON", f_mid, (255, 232, 160))

    dur = now - q.t_on
    d.rectangle([28, 126, W - 28, 258], fill=(92, 6, 6), outline=(255, 190, 190))
    roman, word = mmi_of(v)
    rows = [(("ระดับความรุนแรง" if thai else "INTENSITY"),
             f"{roman}  {word}" if thai else roman),
            ("ตอนนี้" if thai else "NOW", f"{fmt_v(v)} {VLAB}"),
            ("สูงสุด" if thai else "PEAK", f"{fmt_v(q.peak)} {VLAB}"
             + ("  +" if q.clipped else "")),
            ("นานแล้ว" if thai else "DURATION", f"{int(dur//60):d}:{int(dur%60):02d}"),
            ("เริ่มเมื่อ" if thai else "STARTED",
             datetime.fromtimestamp(q.t_on).strftime("%H:%M:%S"))]
    yy = 132
    for k, val in rows:
        d.text((44, yy + 3), k, font=f_sm, fill=(255, 190, 190))
        d.text((188, yy), val, font=f_mid, fill=(255, 255, 255))
        yy += 25 if len(rows) <= 4 else 24

    if q.clipped:
        ctext(d, W, 262,("+ แรงเกินที่เครื่องวัดได้ (เกิน %.1f mm/s)" % CLIP_MMS) if thai
              else "+ OVER RANGE - stronger than %.1f mm/s" % CLIP_MMS,
              f_sm, (255, 225, 130))
    ctext(d, W, H - 28, "จอนี้จะหายเองเมื่อการสั่นสงบลง" if thai
          else "This screen clears itself when shaking stops", f_sm, (255, 205, 205))


def quake_warn_text(q, v, now, thai):
    """ข้อความเตือนระดับ 1 — เอาไปวางแทนบรรทัด fs/axes ในหัวจอ
    ไม่สร้างแถบใหม่ทับกราฟหรือทับนาฬิกา"""
    val = f"{fmt_v(v)}"
    dur = int(now - q.t_on)
    return (f"! สั่นผิดปกติ  {val} {VLAB}  ต่อเนื่อง {dur} วิ" if thai
            else f"! SHAKING  {val} {VLAB}  for {dur}s")


# ---------------------------------------------------------------- หัวจอ
def header(d, W, TOP, s, ok, pvs, page, fonts, touch=None, warn=None,
           muted=False):
    """หัวจอ — ถ้า warn ไม่ว่าง จะเปลี่ยนพื้นเป็นสีเหลืองอำพันทั้งแถบ
    แล้วเอาข้อความเตือนไปแทนบรรทัด fs/axes (ตอนมีเหตุ ตัวเลข fs ไม่สำคัญเท่า)"""
    f_big, f_mid, f_sm = fonts
    amber = warn is not None
    d.rectangle([0, 0, W, TOP - 4], fill=(178, 128, 6) if amber else (18, 22, 30))
    clock = datetime.now().strftime("%H:%M:%S")
    d.text((8, 3), clock, font=f_big, fill=(30, 22, 0) if amber else (240, 242, 250))
    d.text((14 + d.textlength(clock, font=f_big), 9),
           datetime.now().strftime("%d/%m/%Y"), font=f_sm,
           fill=(92, 68, 4) if amber else DIMTXT)
    # เก็บเป็นช่องแยก แล้วค่อยตัดท้ายทิ้งถ้ายาวเกินที่ว่าง
    # ข้อความไทยยาวกว่าอังกฤษ ถ้าต่อกันดื้อ ๆ จะล้นไปทับตัวเลข PVS
    # ตัวเลขแรกคืออัตราการอ่านค่าจากเซนเซอร์ ไม่ใช่ความถี่ของการสั่น
    # เขียนหน่วยเป็น Hz เฉย ๆ คนอ่านมักเข้าใจผิดว่าเป็นความถี่ที่วัดได้
    fields = [L(f"อ่าน {s.fs:.0f} ครั้ง/วิ", f"{s.fs:.1f} Hz"),
              L(f"แกน {sum(ok.values())}/3", f"axes {sum(ok.values())}/3")]
    if GEO_CORRECT:
        fields.append(L(f"ชดเชย>{GEO_FTARGET:g}Hz", f"geo>{GEO_FTARGET:g}Hz")
                      if getattr(s, "filt", None) else L("ไม่ชดเชย", "geo--"))
    if AUTO_PAGE:
        fields.append(L("สลับ", "auto"))
    if getattr(s, "uptime", ""):
        fields.append(L(f"เปิด {s.uptime}", f"up {s.uptime}"))
    if muted:                                # บอกว่าทำไมแรงถึงเกณฑ์แล้วไม่เตือน
        fields.insert(0, L("ไม่เตือน: กิจกรรมมนุษย์", "muted: human"))
    room = W - 178 - 14                      # ถึงตรงที่ข้อความ PVS เริ่ม
    while len(fields) > 1 and d.textlength("  ".join(fields), font=f_sm) > room:
        fields.pop()                         # ตัดช่องท้ายสุดทิ้งทีละช่อง
    info = "  ".join(fields)
    if s.err:
        info = L(f"ADC ผิดพลาด: {s.err[:30]}", f"ADC error: {s.err[:32]}")
    if amber:
        info = warn
    d.text((8, 27), info, font=f_sm,
           fill=(28, 20, 0) if amber else ((255, 120, 120) if s.err else (130, 140, 160)))
    d.text((W - 178, 4), L(f"แรงสั่นรวม {fmt_v(pvs)} {VLAB}",
                           f"PVS {fmt_v(pvs)} {VLAB}"), font=f_mid,
           fill=(40, 28, 0) if amber else (255, 212, 92))
    d.text((W - 172, 26), page, font=f_sm,
           fill=(70, 50, 2) if amber else (110, 150, 210))
    if TOUCH_DEBUG and touch is not None:
        down, pos, cnt = touch
        d.ellipse([W - 20, 27, W - 10, 37],
                  fill=(80, 255, 120) if down else (55, 62, 76))
        info = f"{pos[0]},{pos[1]}" if pos else "--"
        d.text((W - 92, 26), f"t{cnt} {info}", font=f_sm, fill=(95, 105, 125))


# ---------------------------------------------------------------- LIVE
LIVE_AXIS = 15              # ความสูงแถบตัวเลขแกนนอนใต้กราฟ (เท่ากันทั้งสามสไตล์)


def hit_live_lane(H, TOP, y):
    """แตะหน้า LIVE ตรงช่องของแกนไหน — ทั้งสามสไตล์แบ่งพื้นที่เป็นสามช่องเท่ากันหมด"""
    plot = H - TOP - LIVE_AXIS
    if plot <= 0 or y < TOP or y >= TOP + plot:
        return None
    return NAMES[min(len(NAMES) - 1, int((y - TOP) / (plot / len(NAMES))))]


def page_axis(d, W, H, TOP, name, st, ok, s, fonts, thai):
    """แตะกราฟแกนไหนบนหน้า LIVE ก็มาหน้านี้ — แยกความถี่ของแกนนั้นแบบสด ๆ

    สเปกตรัมถูกระบายสีตามย่าน: ย่านธรรมชาติกับย่านกิจกรรมมนุษย์คนละสี
    จึงเห็นได้ทันทีว่าพลังงานไปกองอยู่ฝั่งไหน
    """
    f_big, f_mid, f_sm = fonts
    col = COLORS[name] if ok[name] else GREY
    fs = max(s.fs, 1.0)
    nyq = fs / 2.0

    d.rounded_rectangle([12, TOP + 2, 32, TOP + 18], 3, fill=col)
    d.text((18, TOP + 3), name, font=f_sm, fill=(12, 14, 18))

    back = ("แตะเพื่อกลับหน้าสด" if thai else "tap to go back")
    if not ok[name] or st[name]["sp"] is None:
        d.text((40, TOP + 3), (f"แกน {name} ยังไม่มีเซ็นเซอร์ต่ออยู่" if thai
                               else f"axis {name}: no sensor"),
               font=f_mid, fill=DIMTXT)
        d.text((14, H - 16), back, font=f_sm, fill=(110, 150, 210))
        return

    g = source_split(live_bucket(st, ok))
    a = axis_split(st, ok, name, g)

    d.text((40, TOP + 3),
           (f"พีค {fmt_v(st[name]['pk'])} {VLAB}"
            f"   ความถี่หลัก {st[name]['dom']:.1f} Hz"
            f"   อ่าน {fs:.0f} ครั้ง/วินาที" if thai
            else f"peak {fmt_v(st[name]['pk'])} {VLAB}"
                 f"   dom {st[name]['dom']:.1f} Hz   fs {fs:.0f}"),
           font=f_sm, fill=(150, 160, 180))

    if a is None:
        d.text((14, TOP + 26), ("ยังไม่มีพลังงานในย่านที่วิเคราะห์" if thai
                                else "no energy in analysed bands"),
               font=f_mid, fill=DIMTXT)
        d.text((14, H - 16), back, font=f_sm, fill=(110, 150, 210))
        return

    d.text((12, TOP + 20), a["label"] if thai else a["label_en"],
           font=f_big, fill=a["col"])
    d.text((12, TOP + 48),
           (f"ดัชนีกิจกรรมมนุษย์ {a['score']*100:.0f} / 100"
            f"      {hv_phrase(a['hv'], short=True)}" if thai
            else f"human index {a['score']*100:.0f}/100      "
                 f"{hv_phrase(a['hv'], short=True)}"),
           font=f_sm, fill=(140, 150, 170))
    if a["quiet"]:
        qt = (f"! เบากว่า {fmt_v(SRC_FLOOR)} {VLAB} — ผลยังไม่น่าเชื่อถือ" if thai
              else "! below noise floor")
        d.text((W - 6 - d.textlength(qt, font=f_sm), TOP + 26), qt,
               font=f_sm, fill=(255, 196, 96))

    # ---------------- สเปกตรัมระบายสีตามย่าน ----------------
    px0, px1 = 46, W - 8
    py0, py1 = TOP + 64, H - 58
    pw = px1 - px0
    d.rectangle([px0, py0, px1, py1], outline=(45, 52, 66))

    nat_lo, nat_hi = SRC_NAT[0], min(SRC_NAT[1], nyq * 0.95)
    hum_lo, hum_hi = min(SRC_HUM[0], nat_hi), min(SRC_HUM[1], nyq * 0.95)
    # แสดงแค่พอเลยขอบย่านบนนิดเดียว ย่านธรรมชาติจะได้กว้างพอใส่ป้ายชื่อได้
    fmax = max(min(nyq, hum_hi * 1.05), nat_hi * 1.5)

    sp = st[name]["sp"]
    cut = int(np.clip(len(sp) * fmax / nyq, 8, len(sp)))
    seg = sp[:cut]
    if cut >= pw:                       # ช่องความถี่มากกว่าพิกเซล -> เอายอดของแต่ละช่วง
        edge = np.linspace(0, cut, pw + 1).astype(int)
        colv = np.maximum.reduceat(seg, edge[:-1])
    else:                               # ช่องน้อยกว่าพิกเซล -> ลากเส้นเชื่อม
        colv = np.interp(np.linspace(0, cut - 1, pw), np.arange(cut), seg)
    peak = max(float(colv.max()), 1e-12) * 1.15
    pts = [(px0 + i, py1 - min(colv[i] / peak, 1.0) * (py1 - py0)) for i in range(pw)]

    def xf(f):
        return px0 + min(max(f, 0.0), fmax) / fmax * pw

    grey = (84, 92, 110)
    for lo, hi, c in ((0.0, nat_lo, grey), (nat_lo, nat_hi, SRC_COL_NAT),
                      (hum_lo, hum_hi, SRC_COL_HUM), (hum_hi, fmax, grey)):
        i0, i1 = int(xf(lo) - px0), int(xf(hi) - px0)
        if i1 - i0 < 2:
            continue
        d.rectangle([px0 + i0, py0 + 1, px0 + i1, py1 - 1],
                    fill=tuple(int(ch * 0.10) for ch in c))
        d.polygon([(px0 + i0, py1)] + pts[i0:i1] + [(px0 + i1 - 1, py1)],
                  fill=tuple(int(ch * 0.50) for ch in c))
    d.line(pts, fill=(228, 234, 246))
    for f in (nat_lo, nat_hi, hum_hi):
        if 0 < f < fmax:
            d.line([(xf(f), py0 + 1), (xf(f), py1 - 1)], fill=(72, 82, 100))

    for lo, hi, c, lb in ((nat_lo, nat_hi, SRC_COL_NAT, "ธรรมชาติ" if thai else "natural"),
                          (hum_lo, hum_hi, SRC_COL_HUM, "มนุษย์" if thai else "human")):
        tw = d.textlength(lb, font=f_sm)
        if xf(hi) - xf(lo) > tw + 4:
            d.text(((xf(lo) + xf(hi)) / 2 - tw / 2, py0 + 3), lb, font=f_sm, fill=c)

    for frac in (1.0, 0.5):             # สเกลแกนตั้ง (แอมพลิจูด — หน่วยบอกไว้บรรทัดบน)
        yy = py1 - frac * (py1 - py0)
        lb = fmt_tick(peak * frac * MM_TO_U)
        d.text((max(1, px0 - 4 - d.textlength(lb, font=f_sm)), yy - 2), lb,
               font=f_sm, fill=(95, 105, 125))

    hzw = d.textlength("Hz", font=f_sm)
    step = 10 if fmax <= 70 else 20     # สเกลแกนนอน (ความถี่)
    hz = 0
    while hz <= fmax:
        x = xf(hz)
        lb = str(hz)
        tw = d.textlength(lb, font=f_sm)
        if px0 - 2 <= x - tw / 2 and x + tw / 2 <= px1 - hzw - 6:
            d.line([(x, py1), (x, py1 + 3)], fill=(110, 120, 140))
            d.text((x - tw / 2, py1 + 3), lb, font=f_sm, fill=(118, 128, 148))
        hz += step
    d.text((px1 - hzw, py1 + 3), "Hz", font=f_sm, fill=(90, 100, 120))

    # ---------------- แถบสัดส่วน + ตัวเลข ----------------
    by, bh = H - 40, 16
    wn = int((px1 - 12) * (1.0 - a["frac_hum"]))
    d.rectangle([12, by, 12 + wn, by + bh], fill=SRC_COL_NAT)
    d.rectangle([12 + wn, by, px1, by + bh], fill=SRC_COL_HUM)
    d.rectangle([12, by, px1, by + bh], outline=(70, 80, 98))
    lt = (f"ธรรมชาติ {(1-a['frac_hum'])*100:.0f}%" if thai
          else f"natural {(1-a['frac_hum'])*100:.0f}%")
    if d.textlength(lt, font=f_sm) + 8 >= wn:          # ช่องแคบ เหลือแค่ตัวเลข
        lt = f"{(1-a['frac_hum'])*100:.0f}%"
    if d.textlength(lt, font=f_sm) + 8 < wn:
        d.text((17, by + 2), lt, font=f_sm, fill=(8, 28, 26))
    rt = (f"มนุษย์ {a['frac_hum']*100:.0f}%" if thai
          else f"human {a['frac_hum']*100:.0f}%")
    if d.textlength(rt, font=f_sm) + 8 >= px1 - 12 - wn:
        rt = f"{a['frac_hum']*100:.0f}%"
    if d.textlength(rt, font=f_sm) + 8 < px1 - 12 - wn:
        d.text((px1 - d.textlength(rt, font=f_sm) - 5, by + 2), rt,
               font=f_sm, fill=(32, 18, 2))

    d.text((14, H - 18),
           (f"{nat_lo:g}–{nat_hi:g} Hz {fmt_v(a['nat'])}"
            f"   {hum_lo:g}–{hum_hi:g} Hz {fmt_v(a['hum'])} {VLAB}" if thai
            else f"nat {fmt_v(a['nat'])}  hum {fmt_v(a['hum'])} {VLAB}"),
           font=f_sm, fill=(170, 180, 198))
    d.text((W - 6 - d.textlength(back, font=f_sm), H - 18), back,
           font=f_sm, fill=(110, 150, 210))




def page_wave(img, d, W, H, TOP, data, ok, s, wave, fonts, vlab):
    """คลื่นตามเวลา: แกนตั้งเป็นความเร็ว แกนนอนเป็นเวลา ค่าใหม่เข้าทางขวา"""
    f_sm = fonts[2]
    LM, AXIS = 62, 15                       # ขอบซ้ายไว้ใส่สเกลกับป้ายหน่วย
    plot = H - TOP - AXIS
    lane = int(plot / 3)
    sw = W - LM - 4
    nseg = max(1, int(max(s.fs, 1.0) / FPS) + 4)

    for j, n in enumerate(NAMES):
        y0 = TOP + lane * j
        y1 = y0 + lane - 2
        mid = (y0 + y1) / 2
        d.rectangle([LM, y0, W - 3, y1], outline=(48, 96, 120))
        col = COLORS[n] if ok[n] else GREY

        if not ok[n]:
            msg = L(f"ไม่พบเซ็นเซอร์   (ค้นหาใหม่ทุก {int(RESCAN)} วิ)",
                      f"NO SENSOR   (auto-detect every {int(RESCAN)}s)")
            d.text((LM + (sw - d.textlength(msg, font=f_sm)) / 2, mid - 7),
                   msg, font=f_sm, fill=GREY)
            d.rounded_rectangle([LM + 4, y0 + 3, LM + 21, y0 + 18], 3, fill=col)
            d.text((LM + 9, y0 + 4), n, font=f_sm, fill=(12, 14, 18))
            continue

        w = wave.get(n)
        if w is None or w.w != sw:
            w = wave[n] = WaveTrace(sw, WAVE_SPAN)
        v = transform(data[n] - data[n].mean(), s.fs)
        w.feed(v[-nseg:])

        half = (y1 - y0) / 2 - 2
        sc = w.scale * 1.25
        # เส้นประแบ่งเวลา
        for secs in (30, 60, 90, 120, 150, 180):
            if secs >= WAVE_SPAN:
                break
            x = W - 3 - secs / WAVE_SPAN * sw
            if x <= LM:
                break
            for yy in range(int(y0) + 2, int(y1), 7):
                d.line([(x, yy), (x, yy + 3)], fill=(70, 78, 92))
        d.line([(LM, mid), (W - 3, mid)], fill=(38, 46, 58))

        # คลื่น (วาดเฉพาะช่วงที่มีข้อมูลแล้ว)
        k = sw - w.filled
        yh = mid - np.clip(w.hi / sc, -1, 1) * half
        yl = mid - np.clip(w.lo / sc, -1, 1) * half
        for i in range(k, sw):
            d.line([(LM + 1 + i, yh[i]), (LM + 1 + i, yl[i])], fill=col)

        # สเกลแกนตั้ง
        step = nice_step(sc, 2)
        t = 0.0
        while t <= sc * 1.02:
            for sgn in ((1, -1) if t > 0 else (1,)):
                yy = mid - sgn * (t / sc) * half
                if y0 + 4 <= yy <= y1 - 4:
                    d.line([(LM - 4, yy), (LM, yy)], fill=(95, 105, 125))
                    lb = fmt_tick(sgn * t)
                    d.text((LM - 8 - d.textlength(lb, font=f_sm), yy - 7), lb,
                           font=f_sm, fill=(150, 160, 180))
            t += step

        img.paste(vlab, (2, int(mid - vlab.height / 2)))
        d.rounded_rectangle([LM + 4, y0 + 3, LM + 21, y0 + 18], 3, fill=col)
        d.text((LM + 9, y0 + 4), n, font=f_sm, fill=(12, 14, 18))

    # ---- แกนเวลา ----
    ay = TOP + lane * 3
    d.rectangle([0, ay, W - 1, ay + AXIS], fill=(15, 18, 24))
    for secs in (0, 30, 60, 90, 120, 150, 180):
        if secs > WAVE_SPAN:
            break
        x = W - 3 - secs / WAVE_SPAN * sw
        lb = "now" if secs == 0 else f"-{secs}s"
        lw = d.textlength(lb, font=f_sm)
        if x - lw < LM:
            break
        d.line([(x, ay), (x, ay + 3)], fill=(110, 120, 140))
        d.text((x - lw, ay + 2), lb, font=f_sm, fill=(125, 135, 155))




# ======================================================================
# แยกแหล่งกำเนิดการสั่น
# ======================================================================
def history_buckets(hist, hours):
    """รวมสถิติรายนาทีเป็นถังละ SRC_BUCKET_MIN นาที

    ขอบถังถูกจัดให้ตรงกับเวลานาฬิกา (:00 :15 :30 :45) ไม่ใช่นับถอยจากเวลาปัจจุบัน
    แท่งกราฟจึงไม่เลื่อนไปมาทุกเฟรม และอ้างอิงกับเวลาจริงได้

    คืน (t_from, t_end, bucket_sec, [ถัง...])  ถังที่ไม่มีข้อมูลเป็น None
    """
    bs = max(60.0, SRC_BUCKET_MIN * 60.0)
    nb = max(1, int(round(hours * 3600.0 / bs)))
    t_end = (int(time.time() // bs) + 1) * bs      # ขอบขวาของถังที่กำลังเก็บอยู่
    t_from = t_end - nb * bs

    buckets = [None] * nb
    for r in hist.rows:
        if r["epoch"] < t_from:
            continue
        i = int((r["epoch"] - t_from) // bs)
        if not 0 <= i < nb:
            continue
        b = buckets[i]
        if b is None:
            b = buckets[i] = {
                "t0": t_from + i * bs, "t1": t_from + (i + 1) * bs, "cnt": 0,
                "pvs": 0.0,
                "pk": {n: 0.0 for n in NAMES}, "dom": {n: 0.0 for n in NAMES},
                "nat": {n: 0.0 for n in NAMES}, "hum": {n: 0.0 for n in NAMES}}
        b["cnt"] += 1
        b["pvs"] = max(b["pvs"], r["pvs"])
        for n in NAMES:
            if r[f"{n}_pk"] >= b["pk"][n]:
                b["pk"][n] = r[f"{n}_pk"]
                b["dom"][n] = r[f"{n}_dom"]      # ความถี่หลักของนาทีที่แรงสุดในถัง
            b["nat"][n] += r[f"{n}_nat"] ** 2
            b["hum"][n] += r[f"{n}_hum"] ** 2

    for b in buckets:
        if b:
            for n in NAMES:                      # เฉลี่ยกำลังสองแล้วถอดราก = RMS ของถัง
                b["nat"][n] = (b["nat"][n] / b["cnt"]) ** 0.5
                b["hum"][n] = (b["hum"][n] / b["cnt"]) ** 0.5
    return t_from, t_end, bs, buckets


def find_bucket(hist, t0):
    """หาถังที่ขอบซ้ายตรงกับ t0 จากข้อมูลล่าสุด (ถังปัจจุบันจึงอัปเดตตามเวลาจริง)"""
    for b in history_buckets(hist, HISTORY_HOURS)[3]:
        if b and abs(b["t0"] - t0) < 1.0:
            return b
    return None


def hv_index(hv):
    """แปลงสัดส่วน H/V เป็นคะแนน 0..1   (0 = ชี้ธรรมชาติ, 1 = ชี้กิจกรรมมนุษย์)

    ใช้สเกลลอการิทึมเพราะ H/V เป็นอัตราส่วน — 2 เท่าและครึ่งเท่าควรห่างจากกลางเท่ากัน
    """
    if not hv or hv <= 0:
        return None
    a, b = np.log(SRC_HV_HUM), np.log(SRC_HV_NAT)
    return float(np.clip((b - np.log(hv)) / (b - a), 0.0, 1.0))


def hv_phrase(hv, short=False):
    """อธิบาย H/V เป็นภาษาคน

    H/V คืออัตราส่วนการสั่นแนวราบต่อแนวตั้ง ตัวเลขดิบอย่าง "H/V 2.61"
    ไม่ได้บอกอะไรกับคนอ่านเลย จึงแปลงเป็นประโยคว่าสั่นไปทางไหนมากกว่ากัน
    """
    if not hv or hv <= 0:
        return L("ไม่ได้ค่าแนวการสั่น", "no H/V")
    if hv >= 1.15:
        t = L(f"สั่นทางข้างมากกว่าทางดิ่ง {hv:.1f} เท่า",
              f"horizontal {hv:.1f}x vertical")
        return t if short else t + L("  (แบบแผ่นดินไหว)", "  (quake-like)")
    if hv <= 0.87:
        t = L(f"สั่นทางดิ่งมากกว่าทางข้าง {1.0/hv:.1f} เท่า",
              f"vertical {1.0/hv:.1f}x horizontal")
        return t if short else t + L("  (แบบคนหรือเครื่องจักร)", "  (human-like)")
    return L("สั่นทางข้างกับทางดิ่งพอ ๆ กัน", "horizontal = vertical")


def verdict_of(score):
    """แปลงดัชนี 0..1 เป็นคำตัดสิน + สีประจำคำตัดสิน"""
    if score > SRC_T_HUM:
        return "กิจกรรมมนุษย์", "HUMAN ACTIVITY", SRC_COL_HUM
    if score < SRC_T_NAT:
        return "ธรรมชาติ / พื้นโลก", "NATURAL / GROUND", SRC_COL_NAT
    return "ปนกัน แยกไม่ชัด", "MIXED", SRC_COL_MIX


def live_bucket(st, ok):
    """ห่อสถิติสด ๆ ให้หน้าตาเหมือนถังประวัติ จะได้ใช้ source_split ตัวเดียวกันได้"""
    return {"t0": 0.0, "t1": 0.0, "cnt": 1, "pvs": 0.0,
            "pk": {n: st[n]["pk"] if ok[n] else 0.0 for n in NAMES},
            "dom": {n: st[n]["dom"] if ok[n] else 0.0 for n in NAMES},
            "nat": {n: st[n]["nat"] if ok[n] else 0.0 for n in NAMES},
            "hum": {n: st[n]["hum"] if ok[n] else 0.0 for n in NAMES}}


def axis_split(st, ok, n, g):
    """แยกแหล่งกำเนิดของ "แกนเดียว"

    สัดส่วนย่านความถี่คิดจากแกนนั้นล้วน ๆ ส่วน H/V เป็นคุณสมบัติของการเคลื่อนที่
    ทั้งก้อน ไม่มีความหมายถ้าดูแกนเดียว จึงยืมค่าที่คำนวณจากสามแกน (g) มาใช้ร่วม
    """
    if not ok[n]:
        return None
    e_nat = st[n]["nat"] ** 2
    e_hum = st[n]["hum"] ** 2
    tot = e_nat + e_hum
    if tot <= 0.0:
        return None
    frac_hum = e_hum / tot
    hvs = g["hv_score"] if g else None
    score = (frac_hum if hvs is None
             else SRC_W_FREQ * frac_hum + (1.0 - SRC_W_FREQ) * hvs)
    label, label_en, col = verdict_of(score)
    return {"rms": tot ** 0.5, "nat": st[n]["nat"], "hum": st[n]["hum"],
            "frac_hum": frac_hum, "hv": g["hv"] if g else None,
            "hv_score": hvs, "score": score,
            "label": label, "label_en": label_en, "col": col,
            "quiet": tot ** 0.5 < SRC_FLOOR}


def source_split(b):
    """แยกว่าการสั่นในถังนี้มาจากกิจกรรมมนุษย์หรือธรรมชาติ

    ใช้สองหลักฐานรวมกัน
      1. สัดส่วนพลังงานในย่านสูง (SRC_HUM) ต่อพลังงานทั้งหมด  — น้ำหนัก SRC_W_FREQ
      2. สัดส่วนการเคลื่อนที่แกนราบต่อแกนตั้ง H/V              — น้ำหนักที่เหลือ

    คืน None ถ้าถังนั้นไม่มีข้อมูลย่านความถี่เลย (แถวที่บันทึกไว้ก่อนอัปเดตโปรแกรม)
    """
    e_nat = sum(b["nat"][n] ** 2 for n in NAMES)
    e_hum = sum(b["hum"][n] ** 2 for n in NAMES)
    tot = e_nat + e_hum
    if tot <= 0.0:
        return None

    rms = tot ** 0.5
    frac_hum = e_hum / tot

    horiz = [n for n in NAMES if n != SRC_VERT]
    h2 = sum(b["nat"][n] ** 2 + b["hum"][n] ** 2 for n in horiz)
    v2 = b["nat"][SRC_VERT] ** 2 + b["hum"][SRC_VERT] ** 2
    hv = ((h2 / max(len(horiz), 1)) / v2) ** 0.5 if v2 > 0 else None

    hvs = hv_index(hv)
    if hvs is None:
        score = frac_hum                         # ไม่มี H/V ก็ตัดสินด้วยความถี่อย่างเดียว
    else:
        score = SRC_W_FREQ * frac_hum + (1.0 - SRC_W_FREQ) * hvs

    label, label_en, col = verdict_of(score)
    return {"rms": rms, "nat": e_nat ** 0.5, "hum": e_hum ** 0.5,
            "frac_hum": frac_hum, "hv": hv, "hv_score": hvs, "score": score,
            "label": label, "label_en": label_en, "col": col,
            "quiet": rms < SRC_FLOOR}


# ---------------------------------------------------------------- HISTORY
_HIST_VIEW = {}            # เก็บพิกัดที่วาดไว้ล่าสุด ใช้แปลงจุดที่แตะกลับเป็นถังเวลา


def page_history(d, W, H, TOP, hist, ok, fonts, sel_t0=None):
    f_sm = fonts[2]
    AXIS = 15
    plot = H - TOP - AXIS
    x0, x1 = 46, W - 6
    y0, y1 = TOP + 32, TOP + plot - 4           # เว้นสองแถวบนไว้ใส่หัวเรื่องกับคำอธิบายสี
    d.rectangle([x0, y0, x1, y1], outline=(45, 52, 66))

    t_from, t_end, bs, buckets = history_buckets(hist, HISTORY_HOURS)
    span = max(t_end - t_from, 1.0)
    filled = [b for b in buckets if b]

    def xt(t):
        return x0 + (t - t_from) / span * (x1 - x0)

    # สเกลต้องครอบทั้งความสูงแท่ง (PVS) และเส้นค่าพีครายแกน ไม่งั้นเส้นจะปีนทะลุกรอบ
    ymax = max([b["pvs"] * MM_TO_U for b in filled]
               + [b["pk"][n] * MM_TO_U for b in filled for n in NAMES] or [0.0]) * 1.15
    ymax = max(ymax, 1e-3)

    for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
        y = y1 - frac * (y1 - y0)
        d.line([(x0, y), (x1, y)], fill=(30, 36, 46))
        d.text((4, y - 6), fmt_tick(ymax * frac), font=f_sm, fill=(95, 105, 125))

    hr = 3600.0                                  # เส้นและป้ายเวลาทุกชั่วโมงเต็ม
    t = (int(t_from // hr) + 1) * hr
    while t <= t_end + 1:
        x = xt(t)
        d.line([(x, y0), (x, y1)], fill=(28, 34, 44))
        lb = datetime.fromtimestamp(t).strftime("%H:%M")
        lw = d.textlength(lb, font=f_sm)
        d.text((min(max(x - lw / 2, 2), W - lw - 2), y1 + 3), lb,
               font=f_sm, fill=(105, 115, 135))
        t += hr

    # ---- แท่งกราฟ: ความสูง = PVS สูงสุดของถัง, แบ่งสีตามแหล่งกำเนิด ----
    bwid = max(2.0, (x1 - x0) / len(buckets) - 2.0)
    for b in buckets:
        if not b:
            continue
        bx = xt(b["t0"]) + 1
        top = y1 - min(b["pvs"] * MM_TO_U / ymax, 1.0) * (y1 - y0)
        if top > y1 - 1:
            top = y1 - 1                         # ให้เห็นแท่งบาง ๆ แม้ค่าจะเล็กมาก
        sp = source_split(b)
        if sp is None:                           # แถวเก่าที่ยังไม่มีข้อมูลย่านความถี่
            d.rectangle([bx, top, bx + bwid, y1], fill=(58, 66, 80))
        else:
            dim = 0.45 if sp["quiet"] else 1.0   # ช่วงที่เงียบมากหรี่สีลง เพราะผลไม่น่าเชื่อถือ
            cut = y1 - (y1 - top) * sp["frac_hum"]
            d.rectangle([bx, cut, bx + bwid, y1],
                        fill=tuple(int(c * dim) for c in SRC_COL_HUM))
            d.rectangle([bx, top, bx + bwid, cut],
                        fill=tuple(int(c * dim) for c in SRC_COL_NAT))
        if sel_t0 is not None and abs(b["t0"] - sel_t0) < 1.0:
            d.rectangle([bx - 1, top - 2, bx + bwid + 1, y1], outline=(255, 255, 255))

    # ---- เส้นค่าพีคแยกแกน วาดทับบาง ๆ ให้ยังเห็นรายละเอียดรายนาที ----
    rows = [r for r in hist.rows if r["epoch"] >= t_from] if HISTORY_AXIS_LINES else []
    if len(rows) > 1:
        for n in NAMES:
            if not ok[n] and all(r[f"{n}_pk"] == 0 for r in rows):
                continue
            pts = [(xt(r["epoch"]),
                    y1 - min(r[f"{n}_pk"] * MM_TO_U / ymax, 1.0) * (y1 - y0))
                   for r in rows]
            pts = [p for p in pts if x0 - 2 <= p[0] <= x1 + 2]
            if len(pts) > 1:
                d.line(pts, fill=COLORS[n], width=1)

    if not filled:
        msg = "ยังไม่มีข้อมูลย้อนหลัง — บันทึกทุก %d วินาที" % int(LOG_PERIOD)
        d.text(((W - d.textlength(msg, font=f_sm)) / 2, (y0 + y1) / 2 - 7),
               msg, font=f_sm, fill=GREY)

    # ---- แถวที่ 1: หัวเรื่อง   แถวที่ 2: คำอธิบายสี + วิธีใช้ ----
    d.text((6, TOP + 1),
           f"ประวัติความเร็วอนุภาคสูงสุด ย้อนหลัง {HISTORY_HOURS:.0f} ชั่วโมง  ({VLAB})",
           font=f_sm, fill=(168, 178, 198))
    hint = "แตะแท่งเพื่อดูแหล่งกำเนิด"
    d.text((W - 6 - d.textlength(hint, font=f_sm), TOP + 16), hint,
           font=f_sm, fill=(110, 150, 210))

    lx = 6
    for col, lb in ((SRC_COL_NAT, "ธรรมชาติ"), (SRC_COL_HUM, "มนุษย์")):
        d.rectangle([lx, TOP + 19, lx + 9, TOP + 27], fill=col)
        d.text((lx + 13, TOP + 16), lb, font=f_sm, fill=(190, 200, 215))
        lx += 22 + d.textlength(lb, font=f_sm)
    if HISTORY_AXIS_LINES:
        for n in NAMES:
            d.line([(lx, TOP + 23), (lx + 10, TOP + 23)], fill=COLORS[n], width=2)
            d.text((lx + 13, TOP + 16), n, font=f_sm, fill=(190, 200, 215))
            lx += 27

    _HIST_VIEW.update({"x0": x0, "x1": x1, "y0": y0, "y1": y1,
                        "t_from": t_from, "t_end": t_end, "bs": bs,
                        "buckets": buckets})


def hit_history(x, y):
    """จุดที่แตะบนหน้า HISTORY ตกอยู่ในถังไหน — คืน None ถ้าแตะนอกกราฟหรือถังว่าง"""
    v = _HIST_VIEW
    if not v or not (v["x0"] <= x <= v["x1"] and v["y0"] <= y <= v["y1"]):
        return None
    frac = (x - v["x0"]) / max(v["x1"] - v["x0"], 1)
    i = int(frac * (v["t_end"] - v["t_from"]) // v["bs"])
    bl = v["buckets"]
    if not 0 <= i < len(bl):
        return None
    return bl[i]


# ---------------------------------------------------------------- DETAIL
def page_bucket(d, W, H, TOP, b, fonts, thai):
    """รายละเอียดของช่วงเวลาที่เลือกจากหน้า HISTORY — แยกคน / ธรรมชาติ"""
    f_big, f_mid, f_sm = fonts
    sp = source_split(b)
    day = datetime.fromtimestamp(b["t0"]).strftime("%d/%m")
    t0 = datetime.fromtimestamp(b["t0"]).strftime("%H:%M")
    t1 = datetime.fromtimestamp(b["t1"]).strftime("%H:%M")

    d.text((12, TOP + 1),
           (f"ช่วง {day}  {t0} – {t1}   ({b['cnt']} นาทีที่บันทึกไว้)" if thai
            else f"{day}  {t0} - {t1}   ({b['cnt']} min logged)"),
           font=f_sm, fill=(128, 138, 158))
    d.text((W - 150, TOP + 1),
           L(f"แรงสั่นรวม {fmt_v(b['pvs'])} {VLAB}",
             f"PVS {fmt_v(b['pvs'])} {VLAB}"), font=f_sm, fill=(255, 212, 92))

    if sp is None:
        msg = ("ช่วงนี้บันทึกไว้ก่อนเพิ่มการแยกความถี่ จึงไม่มีข้อมูลให้แยก" if thai
               else "Logged before band analysis was added")
        d.text((12, TOP + 34), msg, font=f_mid, fill=DIMTXT)
        d.text((12, H - 18), "แตะที่ใดก็ได้เพื่อกลับ" if thai else "Tap to go back",
               font=f_sm, fill=(100, 110, 130))
        return

    # ---- คำตัดสิน ----
    d.text((12, TOP + 16), sp["label"] if thai else sp["label_en"],
           font=f_big, fill=sp["col"])
    d.text((12, TOP + 44),
           (f"ดัชนีกิจกรรมมนุษย์ {sp['score']*100:.0f} / 100"
            f"   (ย่านความถี่ {SRC_W_FREQ*100:.0f}% + H/V {(1-SRC_W_FREQ)*100:.0f}%)"
            if thai else f"human index {sp['score']*100:.0f}/100"),
           font=f_sm, fill=(140, 150, 170))
    if sp["quiet"]:
        d.text((W - 196, TOP + 22),
               (f"! เบากว่า {fmt_v(SRC_FLOOR)} {VLAB} — ผลยังเชื่อถือไม่ได้" if thai
                else "! below noise floor"), font=f_sm, fill=(255, 196, 96))

    # ---- แถบสัดส่วนพลังงาน ----
    by, bh = TOP + 60, 24
    bx0, bx1 = 12, W - 12
    wn = int((bx1 - bx0) * (1.0 - sp["frac_hum"]))
    d.rectangle([bx0, by, bx0 + wn, by + bh], fill=SRC_COL_NAT)
    d.rectangle([bx0 + wn, by, bx1, by + bh], fill=SRC_COL_HUM)
    d.rectangle([bx0, by, bx1, by + bh], outline=(70, 80, 98))
    lt = f"ธรรมชาติ {(1-sp['frac_hum'])*100:.0f}%" if thai \
        else f"natural {(1-sp['frac_hum'])*100:.0f}%"
    if d.textlength(lt, font=f_sm) + 10 < wn:
        d.text((bx0 + 5, by + 6), lt, font=f_sm, fill=(8, 28, 26))
    rt = f"มนุษย์ {sp['frac_hum']*100:.0f}%" if thai else f"human {sp['frac_hum']*100:.0f}%"
    if d.textlength(rt, font=f_sm) + 10 < (bx1 - bx0 - wn):
        d.text((bx1 - d.textlength(rt, font=f_sm) - 5, by + 6), rt,
               font=f_sm, fill=(32, 18, 2))
    d.text((bx0, by + bh + 2), f"{SRC_NAT[0]:g}–{SRC_NAT[1]:g} Hz",
           font=f_sm, fill=(110, 120, 140))
    lb = f"{SRC_HUM[0]:g}–{SRC_HUM[1]:g} Hz"
    d.text((bx1 - d.textlength(lb, font=f_sm), by + bh + 2), lb,
           font=f_sm, fill=(110, 120, 140))

    # ---- ตารางแยกแกน ----
    ty = by + bh + 18
    cols = [("แกน" if thai else "AX", 14), ("พีค" if thai else "PEAK", 62),
            (f"{SRC_NAT[0]:g}–{SRC_NAT[1]:g} Hz", 142),
            (f"{SRC_HUM[0]:g}–{SRC_HUM[1]:g} Hz", 240),
            ("ถี่หลัก" if thai else "DOM", 345)]
    for lab, cx in cols:
        d.text((cx, ty), lab, font=f_sm, fill=(120, 130, 150))
    ty += 15
    d.line([(10, ty), (W - 10, ty)], fill=(45, 52, 66))
    ty += 4
    for n in NAMES:
        has = (b["nat"][n] + b["hum"][n]) > 0 or b["pk"][n] > 0
        col = COLORS[n] if has else GREY
        d.rounded_rectangle([14, ty, 31, ty + 15], 3, fill=col)
        d.text((19, ty + 1), n, font=f_sm, fill=(12, 14, 18))
        vals = ([f"{fmt_v(b['pk'][n])}", f"{fmt_v(b['nat'][n])}",
                 f"{fmt_v(b['hum'][n])}", f"{b['dom'][n]:.1f} Hz"]
                if has else ["--"] * 4)
        for (lab, cx), v in zip(cols[1:], vals):
            d.text((cx, ty + 1), v, font=f_sm,
                   fill=(215, 222, 235) if has else GREY)
        ty += 18

    # ---- H/V ----
    ty += 4
    if sp["hv"]:
        d.text((14, ty), hv_phrase(sp["hv"]), font=f_sm, fill=(170, 180, 198))
    else:
        d.text((14, ty), (f"ไม่ได้ค่าแนวการสั่น — แกน {SRC_VERT} ไม่มีสัญญาณ" if thai
                          else "H/V unavailable"), font=f_sm, fill=DIMTXT)

    # ---- ข้อจำกัด + วิธีกลับ ----
    d.text((14, H - 34),
           ("การแยกนี้เป็นการประมาณจากย่านความถี่และสัดส่วนแกน ไม่ใช่การยืนยันแหล่งกำเนิด"
            if thai else "Heuristic from band ratio and H/V - not a positive ID"),
           font=f_sm, fill=(100, 110, 130))
    d.text((14, H - 17), "แตะที่ใดก็ได้เพื่อกลับหน้าย้อนหลัง" if thai
           else "Tap anywhere to go back", font=f_sm, fill=(110, 150, 210))


# ---------------------------------------------------------------- SUMMARY
def page_summary(d, W, H, TOP, hist, st, ok, pvs, fonts):
    f_big, f_mid, f_sm = fonts
    y = TOP + 6
    d.text((10, y), f"สรุปค่าพีค ({VLAB})", font=f_mid, fill=(210, 216, 228))
    y += 24

    cols = [("แกน", 12), ("ตอนนี้", 96), ("1 ชม.", 178), ("6 ชม.", 258), ("24 ชม.", 338),
            ("ความถี่", 416)]
    for label, cx in cols:
        d.text((cx, y), label, font=f_sm, fill=(120, 130, 150))
    y += 16
    d.line([(8, y), (W - 8, y)], fill=(45, 52, 66))
    y += 6

    for n in NAMES:
        col = COLORS[n] if ok[n] else GREY
        d.rounded_rectangle([12, y, 29, y + 15], 3, fill=col)
        d.text((17, y + 1), n, font=f_sm, fill=(12, 14, 18))
        if ok[n]:
            vals = [f"{fmt_v(st[n]['pk'])}",
                    f"{fmt_v(hist.stat(1, n)[0])}",
                    f"{fmt_v(hist.stat(6, n)[0])}",
                    f"{fmt_v(hist.stat(24, n)[0])}",
                    f"{st[n]['dom']:.1f} Hz"]
        else:
            vals = ["--"] * 5
        for (label, cx), v in zip(cols[1:], vals):
            d.text((cx, y + 1), v, font=f_sm,
                   fill=(215, 222, 235) if ok[n] else GREY)
        y += 22

    y += 8
    d.line([(8, y), (W - 8, y)], fill=(45, 52, 66))
    y += 8
    mx24 = max([r["pvs"] for r in hist.window(24)] or [0.0])
    when = ""
    for r in hist.window(24):
        if r["pvs"] == mx24 and mx24 > 0:
            when = datetime.fromtimestamp(r["epoch"]).strftime("%d/%m %H:%M")
    d.text((12, y), L(f"แรงสั่นรวมตอนนี้ {fmt_v(pvs)} {VLAB}",
                      f"PVS now {fmt_v(pvs)} {VLAB}"), font=f_mid,
           fill=(255, 212, 92))
    d.text((215, y + 2), f"สูงสุด 24 ชม. {fmt_v(mx24)}" + (f"  เมื่อ {when}" if when else ""),
           font=f_sm, fill=(190, 200, 215))
    y += 26
    span = 0.0
    if len(hist.rows) > 1:
        span = (hist.rows[-1]["epoch"] - hist.rows[0]["epoch"]) / 3600
    d.text((12, y), f"เก็บข้อมูลแล้ว {len(hist.rows)} นาที ({span:.1f} ชม.)   "
                    f"บันทึกทุก {int(LOG_PERIOD)} วินาที",
           font=f_sm, fill=(110, 120, 140))


# ---------------------------------------------------------------- ปุ่ม
def button_rects(W, H):
    if BTN_H <= 0:
        return []
    n = len(PAGES)
    w = W // n
    y = H - BTN_H
    return [(i * w, y, w - 3, BTN_H - 3, PAGES[i]) for i in range(n)]


def draw_buttons(d, W, H, page, fonts):
    f_mid = fonts[1]
    for bx, by, bw, bh, key in button_rects(W, H):
        on = key == page
        d.rounded_rectangle([bx + 2, by, bx + bw, by + bh], 5,
                            fill=(58, 108, 198) if on else (32, 38, 50),
                            outline=(90, 130, 205) if on else (70, 80, 98))
        lbl = PAGE_EN.get(key, key.upper())   # ปุ่มใช้อังกฤษเสมอ สั้นและอ่านง่ายกว่า
        tw = d.textlength(lbl, font=f_mid)
        d.text((bx + 2 + (bw - tw) / 2, by + bh / 2 - 9), lbl, font=f_mid,
               fill=(245, 247, 252) if on else (165, 175, 195))


def hit_button(W, H, x, y):
    """หาปุ่มจากจุดที่แตะ — ใช้ "ช่องเต็ม" ไม่ใช่กรอบที่วาด

    กรอบที่วาดเว้นร่องระหว่างปุ่มไว้ 3 px และเว้นขอบล่างอีก 3 px
    แต่ไดรเวอร์ทัชหนีบพิกัดไม่ให้เกินขอบจอ (y สูงสุดได้แค่ H-1)
    ถ้าคาลิเบรตเลยช่วงไปนิดเดียว ทุกครั้งที่แตะแถบล่างจะได้ y = H-1 พอดี
    ซึ่งตกอยู่ในร่อง 3 px นั้น -> กดยังไงก็ไม่โดนปุ่มสักที
    จึงต้องทดสอบจากช่องเต็ม ให้ทั้งแถบล่างกดได้หมดไม่มีช่องตาย
    """
    if BTN_H <= 0 or y < H - BTN_H:
        return None
    n = len(PAGES)
    return PAGES[int(min(n - 1, max(0, x * n // max(W, 1))))]


# ======================================================================
def main():
    tft = None
    warned = False
    while tft is None:
        try:
            tft = ST7796(bus=C.TFT_BUS, dev=C.TFT_DEV, speed_hz=C.TFT_SPI_HZ,
                         pin_dc=C.TFT_PIN_DC, pin_rst=C.TFT_PIN_RST,
                         rotation=C.TFT_ROTATION, invert=C.TFT_INVERT, bgr=C.TFT_BGR,
                 pin_bl=getattr(C, "TFT_PIN_BL", None))
        except Exception as e:
            print("เปิดจอไม่ได้:", e, flush=True)
            if "busy" in str(e).lower() and not warned:
                # ขาถูกจองอยู่ = มีโปรแกรมอื่นถือฮาร์ดแวร์ค้างไว้
                # ไม่ใช่สายหลุดหรือจอเสีย วนรอเฉย ๆ ไม่มีทางหาย
                pins = [("DC", C.TFT_PIN_DC), ("RST", C.TFT_PIN_RST),
                        ("BL", getattr(C, "TFT_PIN_BL", None))]
                pins = "  ".join(f"{n}=GPIO {p}" for n, p in pins if p is not None)
                print(f"   ขาที่จอใช้: {pins}", flush=True)
                print("   มีโปรแกรมอื่นถือขาพวกนี้อยู่ "
                      "(แอปรอบก่อน โปรแกรมทดสอบ หรือ service)", flush=True)
                print("   กด Ctrl+C ออก แล้วสั่ง  ./stop.sh  "
                      "จากนั้นรันใหม่", flush=True)
                warned = True
            time.sleep(3)

    ts = None
    try:
        ts = XPT2046(bus=C.TS_BUS, dev=C.TS_DEV, speed_hz=C.TS_SPI_HZ,
                     pin_irq=C.TS_PIN_IRQ, cal_file=C.TS_CAL_FILE,
                     width=tft.width, height=tft.height)
        print("ทัชสกรีนพร้อมใช้งาน", flush=True)
    except Exception as e:
        print("!! เปิดทัชไม่ได้:", e, flush=True)

    fonts = (load_font(22), load_font(15), load_font(12))
    W, H, TOP = tft.width, tft.height, 46
    PH = H - BTN_H                      # ความสูงที่หน้ากราฟใช้ได้ (เหนือแถบปุ่ม)
    s = Sampler()
    s.start()
    hist = History()
    wave = {}
    global VLAB
    VLAB = pick_label(fonts[2], VEL_UNIT)
    ulab = pick_label(fonts[2], UNIT_OF[QUANTITY])
    vlab = vtext(None, ulab, fonts[2], (150, 160, 180))
    print(f"หน่วยที่แสดง: {ulab}   ({QUANTITY})", flush=True)

    quake = Quake()
    global THAI
    THAI = font_has_thai(fonts[1])
    thai = THAI
    if QUAKE_ENABLE:
        print(f"เตือนแผ่นดินไหว: เตือน {fmt_v(QUAKE_WARN)} / "
              f"อันตราย {fmt_v(QUAKE_DANGER)} {VLAB}   "
              f"เพดานที่วัดได้ {fmt_v(CLIP_MMS)} {VLAB} (gain {C.ADS_GAIN})",
              flush=True)
        if QUAKE_DANGER >= CLIP_MMS:
            print(f"!! เกณฑ์อันตรายสูงกว่าเพดานที่ ADC วัดได้ — จะพึ่งการชนเพดาน"
                  f"เป็นตัวจุดแทน ถ้าอยากวัดค่าจริงให้ลด ADS_GAIN ใน config.py",
                  flush=True)
    if SRC_ENABLE:
        print(f"แยกแหล่งกำเนิด: ธรรมชาติ {SRC_NAT[0]:g}-{SRC_NAT[1]:g} Hz / "
              f"กิจกรรมมนุษย์ {SRC_HUM[0]:g}-{SRC_HUM[1]:g} Hz   "
              f"H/V แนวตั้ง = แกน {SRC_VERT}   "
              f"เกณฑ์เงียบ {fmt_v(SRC_FLOOR)} {VLAB}   "
              f"แท่งละ {SRC_BUCKET_MIN:g} นาที", flush=True)
    print("ตัวอักษรไทยบนจอ: " + ("ใช้ได้" if thai else
              "ไม่มีฟอนต์ ใช้อังกฤษแทน  (ติดตั้ง: sudo apt install fonts-tlwg-loma)"),
              flush=True)
    if thai and not thai_shaping_ok():
        # ฟอนต์มีอักษรไทย แต่ Pillow วางสระ/วรรณยุกต์เองไม่เป็น
        # ตัวอักษรจะอ่านออก แต่วรรณยุกต์บนตัวสูงอย่าง ปุ๋ย เป้า จะลอยผิดที่
        print("!! วรรณยุกต์ไทยจะวางเพี้ยน — Pillow ตัวนี้ไม่มีตัวจัดวาง Raqm",
              flush=True)
        print("   แก้ด้วย:  sudo apt install libraqm0", flush=True)
        print("             pip3 install --force-reinstall --break-system-packages pillow",
              flush=True)
    t_start = time.time()

    page = PAGES[0]
    sel_t0 = None                       # ขอบซ้ายของถังเวลาที่เลือกไว้บนหน้า HISTORY
    sel_axis = None                     # แกนที่เลือกไว้จากหน้า LIVE
    p_until = time.time() + AUTO_SEC
    touch_cnt = 0
    last_pos = None
    down = False
    was_down = False
    miss = TOUCH_RELEASE        # จำนวนครั้งติดกันที่อ่านไม่เจอนิ้ว
    last_tap = 0.0              # เวลาที่นับการแตะครั้งล่าสุด (ใช้กันการเด้ง)
    next_draw = 0.0
    next_poll = 0.0

    print("เริ่มทำงาน — แตะปุ่มด้านล่างเพื่อเปลี่ยนหน้า (Ctrl+C ออก)", flush=True)

    try:
        while True:
            # ---------- อ่านทัชถี่ ๆ ระหว่างรอวาดเฟรมถัดไป ----------
            if ts is not None and time.time() >= next_poll:
                tnow = time.time()
                next_poll = tnow + TOUCH_POLL
                try:
                    pos = ts.read_touch(TOUCH_SAMPLES)   # อ่านตรงจากชิป ไม่ง้อขา IRQ

                    # จอตัวต้านทานอ่านพลาดเป็นช่วง ๆ ระหว่างที่นิ้วยังแตะอยู่
                    # ถ้านับทุกครั้งที่อ่านไม่เจอว่า "ปล่อยนิ้ว" การแตะครั้งเดียว
                    # จะกลายเป็นหลายครั้ง หน้าที่สลับไป-กลับก็จะเด้งกลับที่เดิม
                    # (ปุ่มล่างไม่เป็นไรเพราะกดซ้ำแล้วได้ผลเดิม แต่ปุ่มกลับเป็นสลับ)
                    if pos is None:
                        miss += 1
                        if miss >= TOUCH_RELEASE:
                            down = was_down = False
                        pos = None
                    else:
                        miss = 0
                        fresh = not was_down
                        down = was_down = True
                        if not fresh or tnow - last_tap < TOUCH_DEBOUNCE:
                            pos = None             # ยังเป็นการกดค้างครั้งเดิม
                        else:
                            last_tap = tnow

                    if pos is not None:            # เริ่มการแตะครั้งใหม่จริง ๆ
                        last_pos = pos
                        touch_cnt += 1
                        hit = hit_button(W, H, *pos)
                        p_until = time.time() + MANUAL_HOLD
                        if hit:
                            page = hit
                            sel_t0 = sel_axis = None
                            print(f"แตะ {pos} -> {hit}", flush=True)
                        elif page == "bucket":          # แตะที่ไหนก็กลับหน้า HISTORY
                            page, sel_t0 = "history", None
                            print(f"แตะ {pos} -> กลับหน้า history", flush=True)
                        elif page == "axis":            # แตะที่ไหนก็กลับหน้า LIVE
                            page, sel_axis = "live", None
                            print(f"แตะ {pos} -> กลับหน้า live", flush=True)
                        elif page == "live":
                            n = hit_live_lane(PH, TOP + (SPEC_H if LIVE_SPEC else 0),
                                              pos[1])
                            if n:
                                page, sel_axis = "axis", n
                                print(f"แตะ {pos} -> แกน {n}", flush=True)
                            else:
                                print(f"แตะ {pos} -> ไม่โดนกราฟแกนไหน", flush=True)
                        elif page == "history":
                            b = hit_history(*pos)
                            if b and b["cnt"]:
                                page, sel_t0 = "bucket", b["t0"]
                                print(f"แตะ {pos} -> ช่วง "
                                      + datetime.fromtimestamp(b["t0"]).strftime("%H:%M"),
                                      flush=True)
                            else:
                                print(f"แตะ {pos} -> ช่วงนั้นไม่มีข้อมูล", flush=True)
                        else:
                            print(f"แตะ {pos} -> ไม่โดนปุ่ม", flush=True)
                except Exception as e:
                    print("touch error:", e, flush=True)
                    ts = None

            now = time.time()
            if now < next_draw:
                time.sleep(0.008)
                continue
            next_draw = now + 1.0 / FPS

            # ---------- วาด ----------
            data, ok = s.snap()
            st, pvs = analyse(data, ok, s.fs)
            hist.feed(st, pvs)

            if AUTO_PAGE and page in PAGES and now >= p_until:
                page = PAGES[(PAGES.index(page) + 1) % len(PAGES)]
                p_until = now + AUTO_SEC
                sel_t0 = None

            img = Image.new("RGB", (W, H), (8, 10, 14))
            d = ImageDraw.Draw(img)
            up = int(now - t_start)
            s.uptime = f"{up//3600:d}:{up//60%60:02d}:{up%60:02d}"

            # ---------- ตัดสินเรื่องแผ่นดินไหว ----------
            qv, qlevel = 0.0, 0
            if QUAKE_ENABLE:
                qv = quake_level(data, ok, s.fs)
                was = quake.level
                # ตัดสินแหล่งกำเนิดจากสัญญาณสด ๆ ชุดเดียวกับที่หน้าแยกแกนใช้
                gnow = source_split(live_bucket(st, ok)) if SRC_ENABLE else None
                is_human = bool(gnow and not gnow["quiet"]
                                and gnow["score"] > SRC_T_HUM)
                qlevel = quake.update(qv, s.clipping(), now, human=is_human)
                if quake.muted and qv >= QUAKE_WARN and not was:
                    print(f"ไม่เตือน — ตัดสินว่าเป็นกิจกรรมมนุษย์  {fmt_v(qv)} {VLAB}"
                          f"  (ดัชนี {gnow['score']*100:.0f}/100)", flush=True)
                if qlevel > was:
                    print(f"!! แผ่นดินไหว ระดับ {qlevel}  {fmt_v(qv)} {VLAB}"
                          + ("  (ชนเพดาน ADC)" if quake.clipped else ""), flush=True)
                elif was and not qlevel and quake.last:
                    t_on, t_off, peak, clipped = quake.last
                    print(f"สงบแล้ว — นาน {t_off-t_on:.0f} วิ  "
                          f"สูงสุด {fmt_v(peak)} {VLAB}"
                          + ("  (เคยชนเพดาน ADC)" if clipped else ""), flush=True)
                    quake.log()

            if qlevel >= 2:                      # จอแดงเต็มจอ ไม่ต้องวาดอย่างอื่น
                page_quake(d, W, H, quake, qv, now, thai)
                tft.blit(img)
                continue

            sel = find_bucket(hist, sel_t0) if page == "bucket" and sel_t0 else None
            if page == "bucket" and sel is None:     # ถังเลื่อนหลุดกรอบเวลาไปแล้ว
                page, sel_t0 = "history", None

            if page == "axis" and sel_axis not in NAMES:
                page, sel_axis = "live", None       # กันกรณีชื่อแกนหลุด

            plabel = (page_name("bucket") if page == "bucket"
                      else (L(f"แกน {sel_axis}", f"LIVE {sel_axis}")
                            if page == "axis" else page_name(page)))
            header(d, W, TOP, s, ok, pvs, plabel, fonts,
                   (down, last_pos, touch_cnt) if ts is not None else (False, None, -1),
                   quake_warn_text(quake, qv, now, thai) if qlevel == 1 else None,
                   muted=quake.muted and qv >= QUAKE_WARN)
            try:
                if page == "live":
                    LTOP = TOP + draw_spec(d, W, TOP, fonts[2])
                    page_wave(img, d, W, PH, LTOP, data, ok, s, wave, fonts, vlab)
                elif page == "history":
                    page_history(d, W, PH, TOP, hist, ok, fonts, sel_t0)
                elif page == "bucket":
                    page_bucket(d, W, PH, TOP, sel, fonts, thai)
                elif page == "axis":
                    page_axis(d, W, PH, TOP, sel_axis, st, ok, s, fonts, thai)
                else:
                    page_summary(d, W, PH, TOP, hist, st, ok, pvs, fonts)
            except Exception:
                traceback.print_exc()
                d.text((10, TOP + 20), L("วาดหน้าจอผิดพลาด", "draw error"),
                       font=fonts[1], fill=(255, 80, 80))
            draw_buttons(d, W, H, {"bucket": "history", "axis": "live"}.get(page, page),
                         fonts)
            tft.blit(img)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            hist.flush()
        except Exception:
            pass
        try:
            if ts:
                ts.close()
        except Exception:
            pass
        tft.fill((0, 0, 0))
        tft.close()


if __name__ == "__main__":
    main()