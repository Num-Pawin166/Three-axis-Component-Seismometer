"""_path.py — ให้สคริปต์ใน tests/ มองเห็นโมดูลในโฟลเดอร์หลักได้"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
