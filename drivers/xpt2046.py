"""
xpt2046.py — ไดรเวอร์ทัชสกรีนตัวต้านทาน XPT2046 / ADS7846
ใช้บัส SPI1 ร่วมกับจอ แต่แยก chip select (CE1 = GPIO17) และมี IRQ ที่ GPIO16
"""

import json
import os
import time
import spidev
from gpiozero import DigitalInputDevice

CMD_X = 0xD0   # อ่านแกน X (12-bit, differential)
CMD_Y = 0x90   # อ่านแกน Y
CMD_Z1 = 0xB0
CMD_Z2 = 0xC0


class XPT2046:
    def __init__(self, bus=1, dev=1, speed_hz=1_000_000, pin_irq=16,
                 cal_file="touch_cal.json", width=480, height=320):
        self.spi = spidev.SpiDev()
        self.spi.open(bus, dev)
        self.spi.mode = 0
        self.spi.max_speed_hz = speed_hz

        self.irq = DigitalInputDevice(pin_irq, pull_up=True) if pin_irq is not None else None
        self.width, self.height = width, height
        self.cal_file = cal_file
        self.cal = self._load_cal()

    # ---------------- raw ----------------
    def _read12(self, cmd):
        r = self.spi.xfer2([cmd, 0x00, 0x00])
        return ((r[1] << 8) | r[2]) >> 3

    def raw(self, samples=7):
        """อ่านค่าดิบ (median filter) -> (x, y, z) หรือ None ถ้าไม่ได้แตะ"""
        xs, ys = [], []
        for _ in range(samples):
            ys.append(self._read12(CMD_Y))
            xs.append(self._read12(CMD_X))
        z1 = self._read12(CMD_Z1)
        z2 = self._read12(CMD_Z2)
        xs.sort(); ys.sort()
        x = xs[len(xs) // 2]
        y = ys[len(ys) // 2]
        if z1 < 10:
            return None
        z = x * (z2 / max(z1, 1) - 1.0)     # ค่าประมาณของ "ความแรงที่กด"
        if not (100 < x < 4000 and 100 < y < 4000):
            return None
        return x, y, z

    def pressed(self):
        """กำลังถูกกดอยู่ไหม — อ่านจากชิปโดยตรง ไม่ใช้ขา IRQ
        (บางบอร์ดขั้วของ T_IRQ กลับด้าน ทำให้ตีความผิด)"""
        return self.raw(3) is not None

    def irq_level(self):
        """ระดับสัญญาณดิบของขา T_IRQ — ไว้ดูตอนไล่ปัญหาเท่านั้น"""
        return None if self.irq is None else int(self.irq.value)

    # ---------------- calibration ----------------
    def _load_cal(self):
        if os.path.exists(self.cal_file):
            with open(self.cal_file) as f:
                return json.load(f)
        # ค่าเริ่มต้นโดยประมาณ — ควรรัน tests/t4_touch.py เพื่อคาลิเบรตจริง
        return {"xmin": 300, "xmax": 3800, "ymin": 300, "ymax": 3800,
                "swap": True, "flip_x": False, "flip_y": True}

    def save_cal(self, cal):
        self.cal = cal
        with open(self.cal_file, "w") as f:
            json.dump(cal, f, indent=2)

    def position(self, samples=7):
        """คืนพิกัดหน้าจอ (px, py) หรือ None"""
        r = self.raw(samples)
        if r is None:
            return None
        x, y, _ = r
        c = self.cal

        # แบบใหม่: เมทริกซ์ affine 2x3  px = a*x + b*y + c ,  py = d*x + e*y + f
        # พจน์ไขว้ (b กับ d) จำเป็น เพราะแกนของแผ่นทัชไม่ได้ตั้งฉากกับแกนจอเป๊ะ
        # แบบเก่าที่ยืดทีละแกนแยกกันแก้ความเอียงนี้ไม่ได้ จะเหลือความคลาดที่มุมเสมอ
        m = c.get("affine")
        if m:
            px = m[0][0] * x + m[0][1] * y + m[0][2]
            py = m[1][0] * x + m[1][1] * y + m[1][2]
            return (int(max(0, min(self.width - 1, px))),
                    int(max(0, min(self.height - 1, py))))

        # แบบเก่า: ยืดทีละแกน — ยังรองรับไฟล์คาลิเบรตเดิมที่มีอยู่
        if c.get("swap"):
            x, y = y, x
            xmin, xmax = c["ymin"], c["ymax"]
            ymin, ymax = c["xmin"], c["xmax"]
        else:
            xmin, xmax = c["xmin"], c["xmax"]
            ymin, ymax = c["ymin"], c["ymax"]
        px = (x - xmin) / max(xmax - xmin, 1) * self.width
        py = (y - ymin) / max(ymax - ymin, 1) * self.height
        if c.get("flip_x"): px = self.width - px
        if c.get("flip_y"): py = self.height - py
        return int(max(0, min(self.width - 1, px))), int(max(0, min(self.height - 1, py)))

    def read_touch(self, samples=3):
        """อ่านพิกัดตรงจากชิป ไม่ใช้ขา IRQ เลย -> ไม่มีปัญหาเรื่องขั้วสัญญาณ
        คืน (x, y) ถ้ากำลังถูกกดจริง มิฉะนั้นคืน None"""
        return self.position(samples)

    def wait_touch(self, timeout=30.0, release=True):
        """รอจนกว่าจะมีการแตะ แล้วคืนพิกัด (บล็อกจนกว่าจะปล่อยนิ้วถ้า release=True)"""
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout:
            if self.pressed():
                pos = self.position()
                if pos:
                    if release:
                        while self.pressed():
                            time.sleep(0.01)
                    return pos
            time.sleep(0.01)
        return None

    def close(self):
        self.spi.close()
        if self.irq is not None:
            self.irq.close()
