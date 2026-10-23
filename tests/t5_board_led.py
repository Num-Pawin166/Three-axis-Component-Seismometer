#!/usr/bin/env python3
"""
t5_board_led.py — ทดสอบไฟ LED บนบอร์ด Raspberry Pi 5 และทำให้เป็นสีส้ม

บอร์ด Pi 5 มีไฟสถานะสองดวงอยู่ในตัวถังเดียวกัน คุมผ่านระบบไฟล์ของลินุกซ์
    /sys/class/leds/PWR   ไฟสีแดง
    /sys/class/leds/ACT   ไฟสีเขียว
ติดพร้อมกันทั้งสองสีจะผสมกันออกมาเป็น "สีส้ม"  (แดง + เขียว = ส้ม)

ปกติไฟสองดวงนี้ถูกระบบจองไว้แสดงสถานะของตัวเองอยู่ (เรียกว่า trigger)
เช่น ACT กะพริบตอนอ่านเขียนการ์ด ถ้าจะสั่งเองต้องเขียน "none" ลง trigger ก่อน
เพื่อปลดการจองนั้นออก แล้วค่อยเขียนความสว่างลง brightness

รัน:  sudo python3 tests/t5_board_led.py           ทดสอบทีละสี แล้วคืนค่าเดิม
      sudo python3 tests/t5_board_led.py keep      ค้างไว้เป็นสีส้ม ไม่คืนค่าเดิม
      sudo python3 tests/t5_board_led.py restore   คืนไฟกลับเป็นค่าปกติของระบบ
      python3 tests/t5_board_led.py --root <dir>   ทดสอบตัวโปรแกรมโดยไม่แตะบอร์ดจริง
"""
import os
import sys
import time

LEDS = "/sys/class/leds"
BAR = "=" * 66

# ชื่อไฟบนบอร์ดที่พบได้ตามรุ่น — เทียบแบบไม่สนตัวพิมพ์เล็กใหญ่
RED_NAMES = ("pwr", "power", "led1", "red")
GREEN_NAMES = ("act", "activity", "led0", "green")


class Led:
    """ไฟหนึ่งดวงบนบอร์ด พร้อมจำค่าเดิมไว้คืนตอนจบ"""

    def __init__(self, root, name):
        self.dir = os.path.join(root, name)
        self.name = name
        self.max = self._read_int("max_brightness", 1)
        self.old_trigger = self._current_trigger()
        self.old_brightness = self._read_int("brightness", 0)

    # ---------------- อ่าน/เขียนไฟล์ ----------------
    def _path(self, f):
        return os.path.join(self.dir, f)

    def _read(self, f, default=""):
        try:
            with open(self._path(f)) as fh:
                return fh.read().strip()
        except OSError:
            return default

    def _read_int(self, f, default=0):
        try:
            return int(self._read(f, str(default)) or default)
        except ValueError:
            return default

    def _write(self, f, value):
        try:
            with open(self._path(f), "w") as fh:
                fh.write(str(value))
            return True
        except PermissionError:
            return False
        except OSError:
            return False

    def _current_trigger(self):
        """ไฟล์ trigger แสดงตัวเลือกทั้งหมด โดยตัวที่ใช้อยู่ครอบด้วยวงเล็บเหลี่ยม"""
        raw = self._read("trigger")
        for tok in raw.split():
            if tok.startswith("[") and tok.endswith("]"):
                return tok[1:-1]
        return "none"

    # ---------------- สั่งงาน ----------------
    def take_control(self):
        """ปลดการจองของระบบ เพื่อให้สั่งความสว่างเองได้"""
        return self._write("trigger", "none")

    def set(self, on):
        return self._write("brightness", self.max if on else 0)

    def set_trigger(self, name):
        return self._write("trigger", name)

    def restore(self):
        # ต้องเขียนความสว่างก่อน แล้วค่อยคืน trigger
        # เพราะเมื่อ trigger ทำงานแล้ว มันจะเข้ามาคุมความสว่างแทนทันที
        self._write("brightness", self.old_brightness)
        self._write("trigger", self.old_trigger)


def find_leds(root):
    """หาไฟแดงกับไฟเขียวบนบอร์ด คืน (red, green, ชื่อทั้งหมดที่เจอ)"""
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return None, None, []

    def pick(cands):
        for want in cands:
            for n in names:
                if n.lower() == want:
                    return n
        for want in cands:                      # เผื่อชื่อมีคำอื่นนำหน้า เช่น led0::act
            for n in names:
                if want in n.lower():
                    return n
        return None

    return pick(RED_NAMES), pick(GREEN_NAMES), names


def need_root(root):
    return root == LEDS and os.geteuid() != 0


def main():
    args = [a for a in sys.argv[1:]]
    root = LEDS
    if "--root" in args:
        i = args.index("--root")
        root = args[i + 1]
        del args[i:i + 2]
    mode = args[0] if args else "test"

    print(f"{BAR}\nไฟ LED บนบอร์ด Raspberry Pi 5\n{BAR}")

    if not os.path.isdir(root):
        print(f"  ไม่พบโฟลเดอร์ {root}")
        print("  เครื่องนี้อาจไม่ใช่ Raspberry Pi หรือเคอร์เนลไม่ได้เปิดส่วนควบคุมไฟ")
        return 1

    red_name, green_name, all_names = find_leds(root)
    print(f"  ไฟที่ระบบมีทั้งหมด: {', '.join(all_names) if all_names else 'ไม่มี'}")
    print(f"  ไฟสีแดง  -> {red_name or 'ไม่พบ'}")
    print(f"  ไฟสีเขียว -> {green_name or 'ไม่พบ'}")

    if not red_name or not green_name:
        print()
        print("  หาไฟไม่ครบทั้งสองสี จึงผสมเป็นสีส้มไม่ได้")
        print("  ถ้าชื่อไฟบนเครื่องไม่ตรงกับที่โปรแกรมรู้จัก ให้เพิ่มชื่อลงใน")
        print("  ตัวแปร RED_NAMES หรือ GREEN_NAMES ที่หัวไฟล์นี้")
        return 1

    if need_root(root):
        print()
        print("  ต้องสั่งด้วยสิทธิ์ root — รันใหม่เป็น")
        print("     sudo python3 tests/t5_board_led.py")
        return 1

    red = Led(root, red_name)
    green = Led(root, green_name)
    print(f"\n  ค่าเดิมก่อนทดสอบ")
    print(f"     {red.name:<6s} trigger = {red.old_trigger:<12s} "
          f"ความสว่าง {red.old_brightness}/{red.max}")
    print(f"     {green.name:<6s} trigger = {green.old_trigger:<12s} "
          f"ความสว่าง {green.old_brightness}/{green.max}")

    # ---------------- คืนค่าเดิมอย่างเดียว ----------------
    if mode == "restore":
        # ค่าปกติของ Raspberry Pi: ไฟเขียวกะพริบตามการ์ด ไฟแดงติดค้าง
        green.set_trigger("mmc0")
        red.set_trigger("default-on")
        print(f"\n{BAR}\n  คืนไฟกลับเป็นค่าปกติของระบบแล้ว\n{BAR}")
        return 0

    ok = red.take_control() and green.take_control()
    if not ok:
        print("\n  เขียนไฟล์ trigger ไม่ได้ — สิทธิ์ไม่พอ ให้ใช้ sudo")
        return 1

    try:
        if mode == "keep":
            red.set(True)
            green.set(True)
            print(f"\n{BAR}")
            print("  ตั้งไฟบนบอร์ดเป็นสีส้มค้างไว้แล้ว")
            print("  ไฟจะเป็นสีส้มจนกว่าจะปิดเครื่องหรือสั่ง restore")
            print()
            print("  ถ้าอยากให้เป็นสีส้มเองทุกครั้งที่เปิดเครื่อง ให้เพิ่มสองบรรทัดนี้")
            print("  ลงใน /boot/firmware/config.txt แล้วรีบูต")
            print("     dtparam=act_led_trigger=none")
            print("     dtparam=act_led_activelow=off")
            print("  (บรรทัดสำหรับไฟแดงคือ pwr_led_trigger / pwr_led_activelow)")
            print(f"{BAR}")
            return 0

        # ---------------- ทดสอบทีละสี ----------------
        print(f"\n{BAR}\n  มองที่ไฟดวงเล็กบนบอร์ด ข้าง ๆ ช่องเสียบไฟ\n{BAR}")
        steps = [("ดับทั้งสองดวง", False, False, 1.5),
                 ("ติดเฉพาะสีแดง", True, False, 2.5),
                 ("ติดเฉพาะสีเขียว", False, True, 2.5),
                 ("ติดพร้อมกัน = สีส้ม", True, True, 4.0)]
        for label, r, g, hold in steps:
            red.set(r)
            green.set(g)
            print(f"  {label:<24s}  แดง {'ติด' if r else 'ดับ'}   "
                  f"เขียว {'ติด' if g else 'ดับ'}")
            time.sleep(hold)

        print("\n  กะพริบสีส้ม 5 ครั้ง")
        for _ in range(5):
            red.set(True); green.set(True); time.sleep(0.35)
            red.set(False); green.set(False); time.sleep(0.35)

        red.set(True)
        green.set(True)
        print("\n  ค้างไว้เป็นสีส้ม 3 วินาทีสุดท้าย")
        time.sleep(3.0)

        print(f"\n{BAR}\n  สรุป\n{BAR}")
        print("  ถ้าเห็นครบทั้งแดง เขียว และส้ม แปลว่าไฟบนบอร์ดสั่งงานได้ปกติ")
        print("  ถ้าเห็นแค่สีเดียว แสดงว่าบอร์ดรุ่นนี้แยกไฟคนละดวง ผสมสีไม่ได้")
        print()
        print("  อยากให้ค้างเป็นสีส้มไว้เลย สั่ง")
        print("     sudo python3 tests/t5_board_led.py keep")
        return 0
    finally:
        if mode != "keep":
            red.restore()
            green.restore()
            print("\n  คืนค่าไฟกลับเป็นของเดิมแล้ว")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nหยุดกลางคัน")
        sys.exit(130)
