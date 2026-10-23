"""
st7796.py — ไดรเวอร์จอ ST7796S (320x480, RGB565) ผ่าน SPI สำหรับ Raspberry Pi 5
ใช้ spidev + gpiozero, วาดภาพด้วย PIL/numpy

ต้องตั้ง spidev.bufsiz=65536 ใน /boot/firmware/cmdline.txt
ไม่อย่างนั้นการส่งภาพเต็มจอจะถูกหั่นเป็นก้อนเล็ก ๆ และช้ามาก (2-3 FPS)
"""

import time
import numpy as np
import spidev
from gpiozero import DigitalOutputDevice
from PIL import Image, ImageDraw, ImageFont

SWRESET = 0x01
SLPOUT  = 0x11
NORON   = 0x13
INVOFF  = 0x20
INVON   = 0x21
DISPON  = 0x29
CASET   = 0x2A
RASET   = 0x2B
RAMWR   = 0x2C
MADCTL  = 0x36
COLMOD  = 0x3A
CSCON   = 0xF0          # ปลด/ล็อกชุดคำสั่งที่สอง (จำเป็นสำหรับ ST7796S)

MAD_MY, MAD_MX, MAD_MV, MAD_ML, MAD_BGR, MAD_MH = 0x80, 0x40, 0x20, 0x10, 0x08, 0x04

# ฟอนต์ที่รองรับภาษาไทยจะถูกลองก่อน (ติดตั้งด้วย: sudo apt install fonts-tlwg-loma)
# แพ็กเกจ fonts-tlwg-* ของ Debian ลง .otf ไว้ใน opentype/ ไม่ใช่ .ttf ใน truetype/
FONT_PATHS = [
    "/usr/share/fonts/opentype/tlwg/Loma.otf",
    "/usr/share/fonts/opentype/tlwg/Garuda.otf",
    "/usr/share/fonts/truetype/tlwg/Loma.ttf",
    "/usr/share/fonts/truetype/tlwg/Garuda.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansThai-Regular.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansThai-Regular.otf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
]


def thai_shaping_ok():
    """Pillow จัดวางสระ/วรรณยุกต์ไทยได้ถูกตำแหน่งหรือยัง

    PIL วางอักษรเองแบบเรียงทีละตัว (BASIC) ซึ่งใช้กับภาษาไทยไม่ได้
    เพราะสระบนกับวรรณยุกต์ต้องขยับตามความสูงของพยัญชนะข้างล่าง
    เช่น "ปุ๋ย" กับ "เป้า" ถ้าไม่มีตัวจัดวาง วรรณยุกต์จะลอยผิดที่
    ตัวจัดวางที่ถูกต้องคือ Raqm (libraqm) ซึ่งต้องมีตอน build Pillow
    """
    try:
        from PIL import features
        return bool(features.check("raqm"))
    except Exception:
        return False


FONT_USED = None        # ไฟล์ฟอนต์ที่เลือกใช้จริง — ไว้ให้ tests/t6_font.py รายงาน


def load_font(size=16):
    """โหลดฟอนต์ โดยบังคับใช้ตัวจัดวาง Raqm ถ้ามี เพื่อให้ภาษาไทยไม่เพี้ยน

    เลือกฟอนต์ที่ "วาดอักษรไทยได้จริง" ก่อนเสมอ
    เช็คแค่ว่าเปิดไฟล์ได้ไม่พอ เพราะ DejaVu เปิดได้แต่ไม่มีอักษรไทย
    จะได้กล่องสี่เหลี่ยมเต็มจอแทนตัวหนังสือ
    """
    global FONT_USED
    layout = ImageFont.Layout.RAQM if thai_shaping_ok() else ImageFont.Layout.BASIC

    def _open(path):
        try:
            return ImageFont.truetype(path, size, layout_engine=layout)
        except Exception:
            pass
        try:                                  # เผื่อฟอนต์นั้นใช้ Raqm ไม่ได้
            return ImageFont.truetype(path, size)
        except Exception:
            return None

    first = None
    for p in FONT_PATHS:                      # รอบแรก เอาเฉพาะตัวที่มีอักษรไทย
        f = _open(p)
        if f is None:
            continue
        if first is None:
            first, first_p = f, p
        if font_has_thai(f):
            FONT_USED = p
            return f
    if first is not None:                     # ไม่มีตัวไหนมีอักษรไทยเลย
        FONT_USED = first_p
        return first
    FONT_USED = "(ฟอนต์สำรองของ PIL)"
    return ImageFont.load_default()


def font_has_thai(font=None):
    """ฟอนต์วาดอักษรไทยได้จริงไหม

    วิธีเดิม (เช็คว่า getmask มี bbox) ใช้ไม่ได้ เพราะฟอนต์ที่ไม่มีอักษรไทย
    จะวาดกล่อง .notdef ออกมาแทน ซึ่งกล่องนั้นก็มี bbox -> ตอบ True เสมอ

    วิธีนี้เทียบรูปของอักษรไทยสองตัวที่หน้าตาต่างกันมาก
    ถ้าฟอนต์ไม่มีทั้งคู่ จะได้กล่อง .notdef รูปเดียวกันเป๊ะ -> ตอบ False ถูกต้อง
    """
    f = font if font is not None else load_font(20)

    def shape(ch):
        im = Image.new("L", (72, 72), 0)
        ImageDraw.Draw(im).text((6, 6), ch, font=f, fill=255)
        return im.tobytes()

    try:
        a, b = shape("ก"), shape("ญ")
        return a != b and max(a) > 0
    except Exception:
        return False


def rgb565(r, g, b):
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)


class ST7796:
    def __init__(self, bus=1, dev=0, speed_hz=40_000_000, pin_dc=27, pin_rst=25,
                 rotation=270, invert=False, bgr=True, pin_bl=None):
        self.spi = spidev.SpiDev()
        self.spi.open(bus, dev)
        self.spi.mode = 0
        self.spi.max_speed_hz = speed_hz

        self.dc = DigitalOutputDevice(pin_dc, initial_value=True)
        self.rst = DigitalOutputDevice(pin_rst, initial_value=True) if pin_rst else None
        # ขา LED ของจอคุมไฟส่องหลัง ถ้าไม่สั่งให้เป็น HIGH จอจะมืดสนิท
        # ทั้งที่ภาพถูกส่งไปแล้ว ดูเหมือนจอเสียทั้งที่จริง ๆ แค่ไฟไม่ติด
        self.bl = DigitalOutputDevice(pin_bl, initial_value=True) if pin_bl is not None else None
        self.rotation = rotation % 360
        self.bgr = bgr
        self.width, self.height = (480, 320) if self.rotation in (90, 270) else (320, 480)
        self._init(invert)

    def backlight(self, on=True):
        """เปิด/ปิดไฟส่องหลังจอ คืน False ถ้าไม่ได้ต่อขานี้ไว้"""
        if self.bl is None:
            return False
        self.bl.on() if on else self.bl.off()   # ใช้ on()/off() ไม่ใช่ .value
        return True

    # ------------------------------------------------------------ ระดับล่าง
    def _cmd(self, c, *args):
        self.dc.off()
        self.spi.writebytes([c & 0xFF])
        if args:
            self.dc.on()
            self.spi.writebytes(list(args))

    def _data(self, buf):
        self.dc.on()
        mv = memoryview(buf)
        step = 60000                      # เผื่อเครื่องที่ยังไม่ได้ขยาย spidev.bufsiz
        for i in range(0, len(mv), step):
            self.spi.writebytes2(mv[i:i + step])

    def _reset(self):
        if self.rst is None:
            return
        self.rst.on(); time.sleep(0.02)
        self.rst.off(); time.sleep(0.05)
        self.rst.on(); time.sleep(0.12)

    def _madctl(self):
        base = MAD_BGR if self.bgr else 0
        return {0: MAD_MX | base,
                90: MAD_MV | base,
                180: MAD_MY | base,
                270: MAD_MV | MAD_MX | MAD_MY | base}[self.rotation]

    def _init(self, invert):
        """ลำดับตั้งค่าเต็มของ ST7796S

        ลำดับสั้น ๆ แค่ SWRESET/SLPOUT/COLMOD/DISPON ใช้ไม่ได้กับพาเนลส่วนใหญ่
        จอจะติดไฟ backlight แต่ไม่รับข้อมูลภาพ เห็นเป็นสีขาวล้วน
        ต้องปลดล็อกชุดคำสั่งที่สอง (0xF0) ตั้งวงจรจ่ายไฟกับ VCOM และใส่ตารางแกมมาก่อน
        """
        self._reset()
        self._cmd(SWRESET); time.sleep(0.12)
        self._cmd(SLPOUT);  time.sleep(0.12)

        self._cmd(CSCON, 0xC3)            # ปลดล็อกชุดคำสั่งที่สอง
        self._cmd(CSCON, 0x96)

        self._cmd(MADCTL, self._madctl())
        self._cmd(COLMOD, 0x55)           # 16 บิตต่อพิกเซล (RGB565)

        self._cmd(0xB4, 0x01)             # โหมดกลับขั้วสัญญาณ: 1 dot inversion
        self._cmd(0xB6, 0x80, 0x02, 0x3B)  # ควบคุมการสแกนจอ
        self._cmd(0xE8, 0x40, 0x8A, 0x00, 0x00, 0x29, 0x19, 0xA5, 0x33)

        self._cmd(0xC1, 0x06)             # วงจรจ่ายไฟภาค 2
        self._cmd(0xC2, 0xA7)             # วงจรจ่ายไฟภาค 3
        self._cmd(0xC5, 0x18)             # ระดับ VCOM
        time.sleep(0.12)

        self._cmd(0xE0, 0xF0, 0x09, 0x0B, 0x06, 0x04, 0x15, 0x2F,
                  0x54, 0x42, 0x3C, 0x17, 0x14, 0x18, 0x1B)   # แกมมาขั้วบวก
        self._cmd(0xE1, 0xF0, 0x09, 0x0B, 0x06, 0x04, 0x03, 0x2D,
                  0x43, 0x42, 0x3B, 0x16, 0x14, 0x17, 0x1B)   # แกมมาขั้วลบ
        time.sleep(0.12)

        self._cmd(CSCON, 0x3C)            # ล็อกชุดคำสั่งที่สองกลับ
        self._cmd(CSCON, 0x69)
        time.sleep(0.12)

        self._cmd(INVON if invert else INVOFF)
        self._cmd(NORON);  time.sleep(0.02)
        self._cmd(DISPON); time.sleep(0.12)
        self.fill((0, 0, 0))

    def _window(self, x0, y0, x1, y1):
        self._cmd(CASET, x0 >> 8, x0 & 0xFF, x1 >> 8, x1 & 0xFF)
        self._cmd(RASET, y0 >> 8, y0 & 0xFF, y1 >> 8, y1 & 0xFF)
        self._cmd(RAMWR)

    # ------------------------------------------------------------ วาดภาพ
    @staticmethod
    def to565(img):
        """PIL RGB -> ไบต์ RGB565 เรียงแบบ big-endian"""
        a = np.asarray(img.convert("RGB"), dtype=np.uint16)
        v = ((a[:, :, 0] & 0xF8) << 8) | ((a[:, :, 1] & 0xFC) << 3) | (a[:, :, 2] >> 3)
        return v.astype(">u2").tobytes()

    def blit(self, img, x=0, y=0):
        """ส่งภาพ PIL ขึ้นจอที่ตำแหน่ง (x, y)"""
        w, h = img.size
        self._window(x, y, x + w - 1, y + h - 1)
        self._data(self.to565(img))

    def fill(self, color=(0, 0, 0)):
        self.blit(Image.new("RGB", (self.width, self.height), color))

    def fill_rect(self, x, y, w, h, color):
        self.blit(Image.new("RGB", (w, h), color), x, y)

    def new_canvas(self, color=(0, 0, 0)):
        img = Image.new("RGB", (self.width, self.height), color)
        return img, ImageDraw.Draw(img)

    def close(self):
        try:
            self.spi.close()
        except Exception:
            pass
        if self.bl is not None:
            try:
                self.bl.off()          # ดับไฟส่องหลังก่อนปล่อยขา
            except Exception:
                pass
        for obj in (self.dc, self.rst, self.bl):
            if obj is not None:
                try:
                    obj.close()
                except Exception:
                    pass