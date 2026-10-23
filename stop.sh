#!/bin/bash
# stop.sh — หยุดทุกอย่างที่คุมฮาร์ดแวร์อยู่ ก่อนลงมือทดสอบ
echo "หยุด service..."
sudo systemctl stop vibe3d 2>/dev/null
echo "ปิดแอปที่รันค้าง..."
pkill -f app_fft.py 2>/dev/null
pkill -f app.py 2>/dev/null
sleep 2
pkill -9 -f app_fft.py 2>/dev/null
pkill -9 -f app.py 2>/dev/null
sleep 1

LEFT=$(ps -eo pid,args | grep -E "app_fft\.py|app\.py" | grep -v grep)
if [ -n "$LEFT" ]; then
    echo "!! ยังเหลือโปรเซสนี้อยู่:"
    echo "$LEFT"
    exit 1
fi
echo "เรียบร้อย ไม่มีอะไรคุมฮาร์ดแวร์แล้ว — ทดสอบได้เลย"
echo
echo "เสร็จแล้วสั่ง  sudo systemctl start vibe3d  เพื่อเริ่มใช้งานจริง"
