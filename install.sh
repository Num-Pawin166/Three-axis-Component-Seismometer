#!/bin/bash
# install.sh — ติดตั้งทุกอย่างหลังลง Raspberry Pi OS ใหม่
# รัน:  cd ~/vibe3d && bash install.sh
set -e

USER_NAME="${SUDO_USER:-$USER}"
HERE="$(cd "$(dirname "$0")" && pwd)"
BOOT=/boot/firmware
[ -d "$BOOT" ] || BOOT=/boot

echo "=============================================="
echo " ติดตั้งระบบวัดแรงสั่นสะเทือน 3 แกน"
echo " ผู้ใช้: $USER_NAME   โฟลเดอร์: $HERE"
echo "=============================================="

# ---------------------------------------------- 0. ตรวจว่าไฟล์ครบก่อน
# touch_cal.json ไม่อยู่ในรายการนี้ เพราะมันถูกสร้างตอนรัน tests/t4_touch.py
# ไม่ใช่ไฟล์ต้นฉบับที่ต้องคัดลอกมา ถ้าไม่มีไดรเวอร์จะใช้ค่าเริ่มต้นไปก่อน
NEED=(config.py vibe3d.service
      drivers/__init__.py drivers/ads1263.py drivers/st7796.py drivers/xpt2046.py
      tests/_path.py tests/t1_bus_check.py tests/t2_ads1263.py tests/t3_display.py
      tests/t4_touch.py tests/sensor_check.py tests/raw_check.py)
MISS=()
for f in "${NEED[@]}"; do
    [ -f "$HERE/$f" ] || MISS+=("$f")
done
if [ "${#MISS[@]}" -gt 0 ]; then
    echo
    echo "!! หยุดก่อน — ไฟล์ในโฟลเดอร์ยังไม่ครบ ขาด ${#MISS[@]} ไฟล์"
    printf '   ขาด: %s\n' "${MISS[@]}"
    echo
    echo "   แปลว่าคัดลอกมาไม่ครบ วิธีที่ชัวร์ที่สุดคือเอาไฟล์ zip ขึ้นมาทั้งก้อน"
    echo "   แล้วแตกบนตัว Pi เอง:"
    echo
    echo "       cd ~ && unzip -o vibe3d_setup.zip && cd ~/vibe3d && bash install.sh"
    echo
    exit 1
fi
echo
echo "[0/5] ไฟล์ครบทั้ง ${#NEED[@]} ไฟล์"

# ---------------------------------------------- 1. แพ็กเกจ
echo
echo "[1/5] ติดตั้งแพ็กเกจที่ต้องใช้"
sudo apt update
sudo apt install -y python3-spidev python3-gpiozero python3-lgpio \
                    python3-numpy python3-pil fonts-tlwg-loma

if [ ! -f "$HERE/touch_cal.json" ]; then
    echo "   หมายเหตุ: ยังไม่มี touch_cal.json — หลังติดตั้งเสร็จให้คาลิเบรตทัชด้วย"
    echo "             python3 tests/t4_touch.py"
fi

# ---------------------------------------------- 2. config.txt
echo
echo "[2/5] เปิดบัส SPI ใน $BOOT/config.txt"
add_cfg() {
    if grep -qE "^\s*$1\s*$" "$BOOT/config.txt"; then
        echo "      มีอยู่แล้ว: $1"
    else
        echo "$1" | sudo tee -a "$BOOT/config.txt" > /dev/null
        echo "      เพิ่ม: $1"
    fi
}
add_cfg "dtparam=spi=on"
# ใช้ spi1-2cs ไม่ใช่ spi1-3cs เพราะแบบ 3cs จะยึด GPIO16 ที่ต้องใช้เป็น T_IRQ
add_cfg "dtoverlay=spi1-2cs"

# ---------------------------------------------- 3. cmdline.txt
echo
echo "[3/5] ขยายบัฟเฟอร์ SPI ใน $BOOT/cmdline.txt"
if grep -q "spidev.bufsiz" "$BOOT/cmdline.txt"; then
    echo "      มีอยู่แล้ว"
else
    sudo cp "$BOOT/cmdline.txt" "$BOOT/cmdline.txt.bak"
    # cmdline.txt ต้องเป็นบรรทัดเดียวเท่านั้น ห้ามขึ้นบรรทัดใหม่
    sudo sed -i '1 s/$/ spidev.bufsiz=65536/' "$BOOT/cmdline.txt"
    echo "      เพิ่ม spidev.bufsiz=65536 (สำรองไฟล์เดิมไว้ที่ cmdline.txt.bak)"
fi

# ---------------------------------------------- 4. สิทธิ์
echo
echo "[4/5] เพิ่มผู้ใช้เข้ากลุ่ม spi และ gpio"
sudo usermod -aG spi,gpio "$USER_NAME" || true
mkdir -p "$HERE/data"

# ---------------------------------------------- 5. service
echo
echo "[5/5] ติดตั้ง service ให้เริ่มเองตอนเปิดเครื่อง"
# เขียนลงไฟล์ชั่วคราวก่อน แล้วตรวจว่าไม่ว่างค่อยย้ายไปจริง
# ถ้าปล่อยให้ไฟล์ unit ว่างเปล่า systemd จะถือว่าถูก mask แล้ว enable ไม่ได้
TMP_UNIT="$(mktemp)"
sed "s|/home/ssslab|/home/$USER_NAME|g; s|User=ssslab|User=$USER_NAME|" \
    "$HERE/vibe3d.service" > "$TMP_UNIT"
if [ ! -s "$TMP_UNIT" ]; then
    rm -f "$TMP_UNIT"
    echo "      !! สร้างไฟล์ service ไม่สำเร็จ — ยกเลิกขั้นนี้"
    exit 1
fi
# ถ้ารอบก่อนเคยเขียนไฟล์ว่างค้างไว้ (ขึ้นว่า masked) ให้ล้างทิ้งก่อน
if [ -e /etc/systemd/system/vibe3d.service ] && [ ! -s /etc/systemd/system/vibe3d.service ]; then
    echo "      พบไฟล์ service ว่างค้างอยู่จากรอบก่อน (systemd มองว่า masked) — ลบทิ้ง"
    sudo rm -f /etc/systemd/system/vibe3d.service
fi
sudo cp "$TMP_UNIT" /etc/systemd/system/vibe3d.service
rm -f "$TMP_UNIT"
sudo systemctl unmask vibe3d 2>/dev/null || true
sudo systemctl daemon-reload
sudo systemctl enable vibe3d
echo "      ติดตั้งแล้ว (ยังไม่เริ่ม — ให้เทสฮาร์ดแวร์ผ่านก่อน)"

echo
echo "=============================================="
echo " เสร็จแล้ว — ต้องรีบูตหนึ่งครั้งก่อนใช้งาน"
echo
echo "   sudo reboot"
echo
echo " หลังรีบูตให้ไล่เทสตามลำดับ"
echo "   python3 tests/t1_bus_check.py"
echo "   python3 tests/t2_ads1263.py"
echo "   python3 tests/t3_display.py"
echo "   python3 tests/t4_touch.py"
echo "   python3 tests/sensor_check.py"
echo
echo " ผ่านครบแล้วค่อย:  sudo systemctl start vibe3d"
echo "=============================================="