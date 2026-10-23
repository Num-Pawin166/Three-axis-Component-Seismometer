# Three-axis Component Seismometer

เครื่องวัดแรงสั่นสะเทือน 3 แกน (X / Y / Z) บน Raspberry Pi 5 แสดงผลสเปกตรัม FFT แบบเรียลไทม์บนจอสัมผัส
และบันทึกสถิติย้อนหลังลงไฟล์ CSV

## ฮาร์ดแวร์

- Raspberry Pi 5
- ADS1263 (ADC 32-bit) ผ่าน SPI0
- จอ ST7796S 480x320 + ทัชสกรีน XPT2046 ผ่าน SPI1
- Geophone 4.5 Hz สามตัว (แนวนอน 2 แกน + แนวตั้ง 1 แกน)

ตารางการต่อสายอยู่ใน [SETUP.md](SETUP.md)

## ความสามารถ

- **LIVE** สเปกตรัม FFT ทั้ง 3 แกนพร้อมนาฬิกา แตะกราฟแกนไหนก็เข้าไปดูแกนนั้นได้
- **AXIS** แยกความถี่ของแกนที่เลือกแบบสด ว่ามาจากกิจกรรมมนุษย์หรือธรรมชาติ
- **HISTORY** ความเร็วอนุภาคสูงสุด (PPV) รายชั่วโมง แตะแท่งกราฟเพื่อดูรายละเอียด
- **SUMMARY** ตัวเลขสรุปของตอนนี้ / 1 ชม. / 24 ชม.
- ชดเชยการตอบสนองของ geophone ให้วัดความถี่ต่ำกว่า 4.5 Hz ได้ถูกต้อง
- ตรวจหาเซ็นเซอร์อัตโนมัติ และสแกนซ้ำทุก 60 วินาทีถ้ามีแกนหลุด
- เตือนแผ่นดินไหวตามเกณฑ์ความเร็ว และบันทึกเหตุการณ์ลง `data/quake.csv`

## โครงสร้างโฟลเดอร์

```
app_fft.py            โปรแกรมหลัก
config.py             ค่าตั้งทั้งระบบ (ขา GPIO, gain, ค่า geophone, จอ)
drivers/              ไดรเวอร์ ADS1263, ST7796, XPT2046
tests/                สคริปต์ทดสอบฮาร์ดแวร์ทีละขั้น (t0 - t5, sensor_check, raw_check)
data/                 history.csv (สถิติรายนาที), quake.csv (เหตุการณ์สั่นแรง)
splash.py, splash_boot.py, splash.raw   หน้าจอตอนบูต
install.sh            สคริปต์ติดตั้งอัตโนมัติ
stop.sh               หยุดทุกโปรเซสที่คุมฮาร์ดแวร์
vibe3d.service        systemd service ของโปรแกรมหลัก
vibe3d-splash.service systemd service ของหน้าจอบูต
touch_cal.json        ค่าคาลิเบรตทัชสกรีน
```

## ติดตั้งแบบย่อ

```bash
git clone https://github.com/Num-Pawin166/Three-axis-Component-Seismometer.git ~/vibe3d
cd ~/vibe3d
bash install.sh
sudo reboot
```

จากนั้นทดสอบฮาร์ดแวร์ตามลำดับ

```bash
bash stop.sh
python3 tests/t1_bus_check.py
python3 tests/t2_ads1263.py
python3 tests/t3_display.py
python3 tests/t4_touch.py
python3 tests/sensor_check.py
```

แล้วเริ่มใช้งานจริง

```bash
sudo systemctl start vibe3d
journalctl -u vibe3d -f
```

รายละเอียดเต็ม ค่าที่ควรได้จากแต่ละการทดสอบ และปัญหาที่เคยเจอ ดูได้ใน [SETUP.md](SETUP.md)

## หมายเหตุ

- Pi 5 ใช้ `RPi.GPIO` ไม่ได้ ต้องใช้ `gpiozero` + `lgpio`
- ต้องใช้ `dtoverlay=spi1-2cs` เท่านั้น เพราะ `spi1-3cs` จะยึด GPIO 16 ที่ใช้เป็น T_IRQ ของทัช
- ต้องตั้ง `spidev.bufsiz=65536` ใน `cmdline.txt` ไม่งั้นจอจะเหลือแค่ 2-3 FPS
