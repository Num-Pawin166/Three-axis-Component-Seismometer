#!/usr/bin/env python3
"""
t1_bus_check.py — ด่านแรก ตรวจว่าระบบปฏิบัติการเปิดบัสให้ครบหรือยัง
ยังไม่แตะฮาร์ดแวร์ใด ๆ รันได้แม้ยังไม่ต่อสายเซ็นเซอร์

รัน:  python3 tests/t1_bus_check.py
"""
import _path  # noqa
import glob
import os
import subprocess
import sys

import config as C

LINE = "-" * 62
ok_all = True


def head(n, t):
    print(f"\n{LINE}\n[{n}] {t}\n{LINE}")


def good(msg):
    print(f"   [ผ่าน] {msg}")


def bad(msg, fix=""):
    global ok_all
    ok_all = False
    print(f"   [ตก ] {msg}")
    if fix:
        print(f"          วิธีแก้: {fix}")


# ------------------------------------------------------------------ 1
head(1, "ไฟล์อุปกรณ์ SPI")
devs = sorted(glob.glob("/dev/spidev*"))
print("   ที่พบ:", " ".join(devs) if devs else "(ไม่พบเลย)")
need = [f"/dev/spidev{C.ADS_BUS}.{C.ADS_DEV}",
        f"/dev/spidev{C.TFT_BUS}.{C.TFT_DEV}",
        f"/dev/spidev{C.TS_BUS}.{C.TS_DEV}"]
for d, what in zip(need, ("ADS1263", "จอ TFT", "ทัชสกรีน")):
    if d in devs:
        good(f"{what} ใช้ {d}")
    else:
        bad(f"{what} ต้องการ {d} แต่ไม่มี",
            "เพิ่ม dtparam=spi=on และ dtoverlay=spi1-2cs ใน /boot/firmware/config.txt แล้วรีบูต")

# ------------------------------------------------------------------ 2
head(2, "ค่าใน /boot/firmware/config.txt")
try:
    txt = open("/boot/firmware/config.txt").read()
except Exception:
    try:
        txt = open("/boot/config.txt").read()
    except Exception:
        txt = ""
        bad("อ่าน config.txt ไม่ได้")
if txt:
    for key, why in (("dtparam=spi=on", "เปิดบัส SPI0 ให้ ADS1263"),
                     ("dtoverlay=spi1-2cs", "เปิดบัส SPI1 สองสายเลือกชิป ให้จอกับทัช")):
        lines = [l.strip() for l in txt.splitlines()
                 if l.strip().startswith(key) and not l.strip().startswith("#")]
        if lines:
            good(f"{key}  ({why})")
        else:
            bad(f"ไม่พบ {key}  ({why})", f"เพิ่มบรรทัด {key} แล้วรีบูต")
    if any(l.strip().startswith("dtoverlay=spi1-3cs") and not l.strip().startswith("#")
           for l in txt.splitlines()):
        bad("พบ spi1-3cs ซึ่งจะยึด GPIO 16 ไปเป็น CE2",
            "เปลี่ยนเป็น spi1-2cs ไม่งั้นไม่เหลือขาให้ T_IRQ ของทัชสกรีน")

# ------------------------------------------------------------------ 3
head(3, "ขนาดบัฟเฟอร์ SPI (มีผลกับความเร็วจอมาก)")
try:
    n = int(open("/sys/module/spidev/parameters/bufsiz").read().strip())
    if n >= 65536:
        good(f"spidev.bufsiz = {n:,} ไบต์")
    else:
        bad(f"spidev.bufsiz = {n:,} ไบต์ (เล็กไป ภาพเต็มจอใช้ 307,200 ไบต์)",
            "เพิ่ม spidev.bufsiz=65536 ต่อท้ายบรรทัดเดียวใน /boot/firmware/cmdline.txt แล้วรีบูต")
except Exception as e:
    bad(f"อ่านค่า bufsiz ไม่ได้: {e}")

# ------------------------------------------------------------------ 4
head(4, "ไลบรารีที่ต้องมี")
for mod, pkg in (("spidev", "python3-spidev"), ("gpiozero", "python3-gpiozero"),
                 ("lgpio", "python3-lgpio"), ("numpy", "python3-numpy"),
                 ("PIL", "python3-pil")):
    try:
        __import__(mod)
        good(mod)
    except Exception:
        bad(f"ไม่มี {mod}", f"sudo apt install -y {pkg}")

# ------------------------------------------------------------------ 5
head(5, "สิทธิ์การเข้าถึงอุปกรณ์")
try:
    groups = subprocess.run(["id", "-nG"], capture_output=True, text=True,
                            timeout=5).stdout.split()
    for g in ("spi", "gpio"):
        if g in groups:
            good(f"ผู้ใช้อยู่ในกลุ่ม {g}")
        else:
            bad(f"ผู้ใช้ไม่ได้อยู่ในกลุ่ม {g}",
                f"sudo usermod -aG {g} $USER แล้วออกจากระบบเข้าใหม่")
except Exception as e:
    print("   ข้ามการตรวจสิทธิ์:", e)

# ------------------------------------------------------------------ 6
head(6, "ฟอนต์ภาษาไทยสำหรับหน้าจอ")
thai = [p for p in glob.glob("/usr/share/fonts/**/*oma*", recursive=True)
        + glob.glob("/usr/share/fonts/**/*NotoSansThai*", recursive=True)]
if thai:
    good(f"พบ {os.path.basename(thai[0])}")
else:
    print("   [เตือน] ไม่พบฟอนต์ไทย — หน้าจอจะใช้ภาษาอังกฤษแทน")
    print("          ถ้าต้องการภาษาไทย: sudo apt install -y fonts-tlwg-loma")

print(f"\n{LINE}")
print("สรุป: ผ่านทั้งหมด ไปต่อที่ tests/t2_ads1263.py ได้เลย" if ok_all
      else "สรุป: ยังมีข้อที่ตก แก้ตามคำแนะนำข้างบนแล้วรันซ้ำ")
print(LINE)
sys.exit(0 if ok_all else 1)
