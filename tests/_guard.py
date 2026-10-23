"""
_guard.py — กันไม่ให้โปรแกรมทดสอบรันชนกับตัวอื่นที่กำลังคุมฮาร์ดแวร์อยู่

ปัญหาที่เคยเจอ: แอปหลักรันค้างอยู่ พอ Sampler เจอ error มันจะวนสร้างไดรเวอร์ใหม่
ทุก 2 วินาที ซึ่งแต่ละครั้งจะกระตุกขา RESET ให้ชิปรีเซ็ต ถ้ารันเทสพร้อมกัน
จะอ่านค่าได้ 0x00 ทั้งหมด แล้วเข้าใจผิดว่าฮาร์ดแวร์เสีย

ตรวจสามชั้น
  1. service vibe3d กำลังทำงานอยู่ไหม
  2. มีโปรเซส app_fft.py / app.py รันค้างอยู่ไหม
  3. ขา GPIO ที่ต้องใช้ ถูกจับไว้โดยใครอยู่หรือเปล่า (ชั้นนี้ชี้ขาดที่สุด)
"""
import os
import subprocess
import sys

APP_NAMES = ("app_fft.py", "app.py")
BAR = "!" * 70


def _service_active():
    try:
        r = subprocess.run(["systemctl", "is-active", "vibe3d"],
                           capture_output=True, text=True, timeout=5)
        return r.stdout.strip() == "active"
    except Exception:
        return False


def _app_processes():
    """หาโปรเซสของแอปหลักที่ยังรันอยู่ (ไม่นับตัวเอง)

    ต้องดูให้ละเอียดกว่าการค้นข้อความทั้งบรรทัด ไม่งั้นจะไปจับ shell ที่แค่
    มีชื่อไฟล์อยู่ในคำสั่ง เช่น  pkill -f app_fft.py  หรือ  nano app_fft.py
    เกณฑ์คือ ต้องเป็นโปรเซส python และมีอาร์กิวเมนต์ที่ชื่อไฟล์ตรงกันเป๊ะ
    """
    found, me = [], os.getpid()
    try:
        pids = [p for p in os.listdir("/proc") if p.isdigit()]
    except Exception:
        return found
    for pid in pids:
        if int(pid) == me:
            continue
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                argv = [a for a in f.read().decode("utf-8", "replace").split("\x00") if a]
        except Exception:
            continue
        if not argv:
            continue
        if "python" not in os.path.basename(argv[0]).lower():
            continue
        if any(os.path.basename(a) in APP_NAMES for a in argv[1:]):
            found.append((pid, " ".join(argv)[:60]))
    return found


def _gpio_busy(pins):
    """ลองจองขาดูว่าว่างจริงไหม — คืนรายชื่อขาที่ถูกจับไว้"""
    busy = []
    try:
        from gpiozero import DigitalInputDevice
    except Exception:
        return busy
    for pin in pins:
        try:
            d = DigitalInputDevice(pin)
            d.close()
        except Exception as e:
            if "busy" in str(e).lower():
                busy.append(pin)
    # ห้ามปิด pin factory ตรงนี้เด็ดขาด
    # gpiozero ใช้ factory ตัวเดียวร่วมกันทั้งโปรแกรม ปิดแล้ว handle จะเป็น None
    # การจองขาครั้งต่อไปจะพังด้วย TypeError ทั้งที่ขาว่างอยู่
    return busy


def require_exclusive(pins=(), what="ฮาร์ดแวร์"):
    """เรียกก่อนเริ่มทดสอบ ถ้ามีตัวอื่นคุมอยู่จะหยุดพร้อมบอกวิธีแก้"""
    svc = _service_active()
    procs = _app_processes()
    busy = _gpio_busy(pins)

    if not (svc or procs or busy):
        return

    print("\n" + BAR)
    print(f"!! หยุดก่อน — มีโปรแกรมอื่นคุม{what} อยู่ รันซ้อนกันแล้วค่าจะมั่ว")
    print("!!")
    if svc:
        print("!!  - service vibe3d กำลังทำงานอยู่")
    for pid, cmd in procs:
        print(f"!!  - โปรเซส PID {pid}: {cmd}")
    if busy:
        print(f"!!  - ขา GPIO ที่ถูกจับไว้: {', '.join(str(p) for p in busy)}")
    print("!!")
    print("!! หยุดทั้งหมดด้วยสามบรรทัดนี้")
    print("!!")
    print("!!     sudo systemctl stop vibe3d")
    print("!!     pkill -f app_fft.py ; pkill -f app.py")
    print("!!     sleep 2")
    print("!!")
    print("!! เทสเสร็จแล้วค่อยสั่ง  sudo systemctl start vibe3d")
    print(BAR + "\n")
    sys.exit(1)
