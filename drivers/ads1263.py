"""
ads1263.py — ไดรเวอร์ ADS1263 / ADS1262 (32-bit delta-sigma ADC) สำหรับ Raspberry Pi 5

ใช้ spidev + gpiozero (ห้ามใช้ RPi.GPIO บน Pi 5 เพราะชิป RP1 ทำให้ใช้ไม่ได้)
โหมดที่ใช้งานจริงในโครงงานนี้คือ one-shot (pulse conversion) ของ ADC1 เท่านั้น

หมายเหตุเรื่องขา START
  ขา START ถูกตรึงไว้ที่ระดับต่ำตลอดเวลา แล้วสั่งแปลงค่าด้วยคำสั่ง START1 แทน
  ตามข้อกำหนดของชิป คำสั่งจะใช้ควบคุมได้ก็ต่อเมื่อขา START อยู่ระดับต่ำ
"""

import time

import spidev
from gpiozero import DigitalInputDevice, DigitalOutputDevice

# ---------------------------------------------------------------- คำสั่ง
CMD_NOP = 0x00
CMD_RESET = 0x06
CMD_START1 = 0x08
CMD_STOP1 = 0x0A
CMD_RDATA1 = 0x12
CMD_SYOCAL1 = 0x16
CMD_SYGCAL1 = 0x17
CMD_SFOCAL1 = 0x19
CMD_RREG = 0x20          # 0x20 | addr
CMD_WREG = 0x40          # 0x40 | addr

# ---------------------------------------------------------------- รีจิสเตอร์
REG_ID = 0x00
REG_POWER = 0x01
REG_INTERFACE = 0x02
REG_MODE0 = 0x03
REG_MODE1 = 0x04
REG_MODE2 = 0x05
REG_INPMUX = 0x06
REG_OFCAL0 = 0x07
REG_OFCAL1 = 0x08
REG_OFCAL2 = 0x09
REG_FSCAL0 = 0x0A
REG_FSCAL1 = 0x0B
REG_FSCAL2 = 0x0C
REG_IDACMUX = 0x0D
REG_IDACMAG = 0x0E
REG_REFMUX = 0x0F
REG_TDACP = 0x10
REG_TDACN = 0x11
REG_GPIOCON = 0x12
REG_GPIODIR = 0x13
REG_GPIODAT = 0x14
REG_ADC2CFG = 0x15
REG_ADC2MUX = 0x16

REG_NAMES = {
    0x00: "ID", 0x01: "POWER", 0x02: "INTERFACE", 0x03: "MODE0", 0x04: "MODE1",
    0x05: "MODE2", 0x06: "INPMUX", 0x07: "OFCAL0", 0x08: "OFCAL1", 0x09: "OFCAL2",
    0x0A: "FSCAL0", 0x0B: "FSCAL1", 0x0C: "FSCAL2", 0x0D: "IDACMUX",
    0x0E: "IDACMAG", 0x0F: "REFMUX", 0x10: "TDACP", 0x11: "TDACN",
    0x12: "GPIOCON", 0x13: "GPIODIR", 0x14: "GPIODAT", 0x15: "ADC2CFG",
    0x16: "ADC2MUX", 0x17: "ADC2OFC0", 0x18: "ADC2OFC1", 0x19: "ADC2FSC0",
    0x1A: "ADC2FSC1",
}

# ---------------------------------------------------------------- รหัส MUX
MUX_AIN0, MUX_AIN1, MUX_AIN2, MUX_AIN3, MUX_AIN4 = 0, 1, 2, 3, 4
MUX_AIN5, MUX_AIN6, MUX_AIN7, MUX_AIN8, MUX_AIN9 = 5, 6, 7, 8, 9
MUX_AINCOM = 0x0A        # ขากลาง (มี VBIAS ป้อนอยู่)
MUX_TEMP = 0x0B          # เซ็นเซอร์อุณหภูมิในชิป
MUX_AVDD = 0x0C          # มอนิเตอร์ไฟเลี้ยงอนาล็อก (อ่านได้ 1/4 ของจริง)
MUX_DVDD = 0x0D          # มอนิเตอร์ไฟเลี้ยงดิจิทัล (อ่านได้ 1/4 ของจริง)
MUX_TDAC = 0x0E
MUX_FLOAT = 0x0F         # ปล่อยลอย — ห้ามใช้วัด noise floor เพราะ PGA จะอิ่มตัว

GAIN_CODE = {1: 0, 2: 1, 4: 2, 8: 3, 16: 4, 32: 5}
RATE_CODE = {2.5: 0x0, 5: 0x1, 10: 0x2, 16.6: 0x3, 20: 0x4, 50: 0x5, 60: 0x6,
             100: 0x7, 400: 0x8, 1200: 0x9, 2400: 0xA, 4800: 0xB, 7200: 0xC,
             14400: 0xD, 19200: 0xE, 38400: 0xF}
FILTER_CODE = {"sinc1": 0, "sinc2": 1, "sinc3": 2, "sinc4": 3, "fir": 4}

FULL = 1 << 31           # ค่าเต็มสเกลของเลข 32 บิตมีเครื่องหมาย


class ADS1263Error(Exception):
    pass


class ADS1263:
    def __init__(self, bus=0, dev=0, speed_hz=2_000_000,
                 pin_reset=12, pin_start=6, pin_drdy=4, vref=2.5):
        self.spi = spidev.SpiDev()
        self.spi.open(bus, dev)
        self.spi.mode = 1                 # ADS126x ใช้ SPI mode 1
        self.spi.max_speed_hz = speed_hz

        self.rst = DigitalOutputDevice(pin_reset, initial_value=True)
        # ตรึง START ไว้ต่ำ แล้วใช้คำสั่ง START1 สั่งแปลงค่าแทน
        self.start = DigitalOutputDevice(pin_start, initial_value=False)
        self.drdy = DigitalInputDevice(pin_drdy, pull_up=None, active_state=True)

        self.vref = vref
        self.gain = 1
        self.rate = 20
        self.filt = "sinc4"
        self.one_shot = False

    # ------------------------------------------------------------ SPI ระดับล่าง
    def _xfer(self, data):
        return self.spi.xfer2(list(data))

    def write_reg(self, addr, value):
        self._xfer([CMD_WREG | (addr & 0x1F), 0x00, value & 0xFF])
        time.sleep(0.0002)

    def read_reg(self, addr):
        return self.read_regs(addr, 1)[0]

    def read_regs(self, start, count):
        r = self._xfer([CMD_RREG | (start & 0x1F), (count - 1) & 0xFF] + [0x00] * count)
        return r[2:2 + count]

    # ------------------------------------------------------------ ควบคุมชิป
    def reset(self):
        """รีเซ็ตด้วยขา RESET แล้วย้ำด้วยคำสั่ง RESET"""
        self.rst.off()
        time.sleep(0.01)
        self.rst.on()
        time.sleep(0.05)
        self._xfer([CMD_RESET])
        time.sleep(0.05)

    def chip_id(self):
        """คืน (ชื่อรุ่น, revision, ค่าดิบของรีจิสเตอร์ ID)"""
        raw = self.read_reg(REG_ID)
        dev = (raw >> 5) & 0x07
        rev = raw & 0x1F
        name = {0x00: "ADS1262", 0x01: "ADS1263"}.get(dev, f"ไม่รู้จัก (0x{dev:02X})")
        # บางล็อตรายงาน DEV_ID ต่างจากเอกสาร จึงยอมรับทั้งสองรุ่น
        if raw == 0x03:
            name = "ADS1262"
        return name, rev, raw

    def configure(self, gain=1, rate=1200, filt="sinc1", one_shot=True):
        """ตั้งค่าหลักของ ADC1"""
        if gain not in GAIN_CODE:
            raise ADS1263Error(f"gain {gain} ไม่รองรับ (ใช้ได้ {sorted(GAIN_CODE)})")
        if rate not in RATE_CODE:
            raise ADS1263Error(f"rate {rate} ไม่รองรับ (ใช้ได้ {sorted(RATE_CODE)})")
        if filt not in FILTER_CODE:
            raise ADS1263Error(f"filter {filt} ไม่รองรับ (ใช้ได้ {sorted(FILTER_CODE)})")

        self.gain, self.rate, self.filt, self.one_shot = gain, rate, filt, one_shot

        # POWER: เปิด internal reference (bit0) + VBIAS ออกที่ AINCOM (bit1)
        self.write_reg(REG_POWER, 0x03)
        # INTERFACE: ส่ง STATUS byte (bit2) + checksum แบบ checksum (bit0)
        self.write_reg(REG_INTERFACE, 0x05)
        # MODE0: bit6 = RUNMODE (1 = pulse / one-shot), delay = 0
        self.write_reg(REG_MODE0, 0x40 if one_shot else 0x00)
        # MODE1: ชนิดตัวกรองดิจิทัล
        self.write_reg(REG_MODE1, (FILTER_CODE[filt] & 0x07) << 5)
        # MODE2: PGA เปิด (bit7 = 0) + gain + data rate
        self.write_reg(REG_MODE2, ((GAIN_CODE[gain] & 0x07) << 4) | (RATE_CODE[rate] & 0x0F))
        # REFMUX: ใช้ internal 2.5 V reference
        self.write_reg(REG_REFMUX, 0x00)
        time.sleep(0.01)

    @property
    def fsr(self):
        """ช่วงวัดเต็มสเกล (โวลต์) — ±fsr"""
        return self.vref / self.gain

    def set_mux(self, p, n):
        self.write_reg(REG_INPMUX, ((p & 0x0F) << 4) | (n & 0x0F))

    def _pulse_start(self):
        """สั่งแปลงค่าหนึ่งครั้ง (ขา START ถูกตรึงต่ำไว้แล้ว)"""
        self._xfer([CMD_START1])

    def wait_drdy(self, timeout=1.0):
        t0 = time.monotonic()
        while self.drdy.value == 1:            # DRDY active-low
            if time.monotonic() - t0 > timeout:
                raise ADS1263Error("DRDY ไม่ลงต่ำภายในเวลาที่กำหนด "
                                   "(ตรวจสายขา DRDY / ไฟเลี้ยง / นาฬิกาคริสตัลบนบอร์ด)")
        return time.monotonic() - t0

    # ------------------------------------------------------------ อ่านข้อมูล
    def read_raw(self, check=True):
        """อ่าน ADC1 ด้วยคำสั่ง RDATA1 -> คืน (raw_int32, status_byte)"""
        r = self._xfer([CMD_RDATA1] + [0x00] * 6)
        status = r[1]
        d = r[2:6]
        chk = r[6]
        if check and ((sum(d) + 0x9B) & 0xFF) != chk:
            raise ADS1263Error("checksum ไม่ตรง — สัญญาณบนบัส SPI ผิดเพี้ยน "
                               "(ลองลด ADS_SPI_HZ หรือตรวจสายให้สั้นลง)")
        raw = (d[0] << 24) | (d[1] << 16) | (d[2] << 8) | d[3]
        if raw & 0x80000000:
            raw -= 1 << 32
        return raw, status

    def convert(self, p, n, check=True):
        """วัดหนึ่งค่าจากคู่ขาที่ระบุ -> คืน (โวลต์, ค่าดิบ, status)"""
        self.set_mux(p, n)
        self._pulse_start()
        self.wait_drdy()
        raw, status = self.read_raw(check)
        return raw * self.fsr / FULL, raw, status

    def scan(self, channels):
        """วัดหลายช่องตามพจนานุกรม {ชื่อ: (p, n)} -> คืน {ชื่อ: โวลต์}"""
        return {name: self.convert(p, n)[0] for name, (p, n) in channels.items()}

    # ------------------------------------------------------------ ฟังก์ชันเสริม
    def read_supply(self, which="AVDD"):
        """วัดไฟเลี้ยง — ชิปส่งมา 1/4 ของค่าจริง ต้องใช้ gain 1"""
        g_old, r_old, f_old = self.gain, self.rate, self.filt
        self.configure(gain=1, rate=400, filt="sinc4", one_shot=True)
        mux = MUX_AVDD if which.upper() == "AVDD" else MUX_DVDD
        self.set_mux(mux, MUX_AINCOM)
        self._pulse_start()
        self.wait_drdy()
        raw, _ = self.read_raw()
        v = raw * self.fsr / FULL * 4.0
        self.configure(gain=g_old, rate=r_old, filt=f_old, one_shot=self.one_shot)
        return v

    def read_temperature(self):
        """อุณหภูมิภายในชิป (°C) — ต้องใช้ gain 1"""
        g_old, r_old, f_old = self.gain, self.rate, self.filt
        self.configure(gain=1, rate=400, filt="sinc4", one_shot=True)
        self.set_mux(MUX_TEMP, MUX_AINCOM)
        self._pulse_start()
        self.wait_drdy()
        raw, _ = self.read_raw()
        mv = raw * self.fsr / FULL * 1000.0
        self.configure(gain=g_old, rate=r_old, filt=f_old, one_shot=self.one_shot)
        return (mv - 122.4) / 0.420 + 25.0

    def self_offset_cal(self):
        """สอบเทียบออฟเซ็ตของตัวเอง (ชิปลัดวงจรอินพุตภายในแล้ววัด)"""
        self._xfer([CMD_SFOCAL1])
        time.sleep(0.2)

    @staticmethod
    def decode_status(s):
        """แปลไบต์ STATUS เป็นข้อความเตือนที่อ่านรู้เรื่อง"""
        flags = []
        if s & 0x40:
            pass                                   # ADC1 มีข้อมูลใหม่ — ปกติ
        if s & 0x20:
            flags.append("EXTCLK (ใช้นาฬิกาภายนอก)")
        if s & 0x10:
            flags.append("REF_ALM (แรงดันอ้างอิงต่ำผิดปกติ)")
        if s & 0x08:
            flags.append("PGAL_ALM (ขาออก PGA ต่ำเกิน)")
        if s & 0x04:
            flags.append("PGAH_ALM (ขาออก PGA สูงเกิน)")
        if s & 0x02:
            flags.append("PGAD_ALM (ผลต่างขาออก PGA เกินช่วง)")
        if s & 0x01:
            flags.append("RESET (ชิปเพิ่งรีเซ็ต)")
        return flags

    def close(self):
        try:
            self._xfer([CMD_STOP1])
        except Exception:
            pass
        for obj in (self.rst, self.start, self.drdy):
            try:
                obj.close()
            except Exception:
                pass
        try:
            self.spi.close()
        except Exception:
            pass
