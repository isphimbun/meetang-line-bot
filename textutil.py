"""ตัวช่วยจัดการข้อความที่พิมพ์เข้ามา (ไม่พึ่งไลบรารีอื่น ทดสอบง่าย)"""
import re

_ZW = dict.fromkeys(map(ord, '\u200b\u200c\u200d\ufeff'), None)


def normalize_text(text):
    """แก้ปัญหาพิมพ์ไทยที่พบบ่อย: 'เเ' (เ สองตัว) → 'แ', ตัดอักขระล่องหน, รวมช่องว่างซ้ำ"""
    t = (text or '').translate(_ZW).replace('เเ', 'แ')
    return re.sub(r'[ \t]+', ' ', t).strip()


def is_dashboard_request(text):
    """ผู้ใช้ขอลิงก์เข้า Dashboard หรือไม่ — รับคำสะกดเพี้ยน เช่น เปิดเเดชบอด / แดชบอร์ด / dashboard / login"""
    t = normalize_text(text).lower().replace(' ', '')
    if not t or len(t) > 30 or re.search(r'\d', t): return False
    if t in ('login', 'ล็อกอิน', 'ล๊อกอิน', 'ลอกอิน', 'เข้าเว็บ', 'เข้าระบบ', 'dashboard', 'dash'): return True
    return 'แดชบอ' in t or 'แดชบอร์ด' in t or 'dashboard' in t
