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


# ---------- วิธีจ่าย (เงินสด / บัตร) ----------
_WITHDRAW_CTX = re.compile(r'ถอน|กดเงิน|แลกเงิน|แลกเยน|เบิกเงิน')
_CASH_RX = r'เงินสด|จ่ายสด|(?<![a-z])cash(?![a-z])|\s+สด$'
_CARD_RX = (r'แตะบัตร|รูดบัตร|ด้วยบัตร|ผ่านบัตร|apple\s*pay|google\s*pay|(?<![a-z])card(?![a-z])|แตะ|รูด|\s+บัตร$')


def extract_pay_method(text):
    """หาวิธีจ่ายจากข้อความ → ('cash'|'card'|None, ข้อความที่ตัดคำบอกวิธีจ่ายออกแล้ว)
    ไม่แตะข้อความที่เป็นการกด/ถอนเงิน และไม่ตีความ "บัตร"/"เครดิต" ทั่วไป (กันชนกับ บัตรคอนเสิร์ต, ค่าบัตรเครดิต)"""
    t = text or ''
    if _WITHDRAW_CTX.search(t): return None, t
    hits = []
    for method, rx in (('cash', _CASH_RX), ('card', _CARD_RX)):
        for m in re.finditer(rx, t, re.I): hits.append((m.start(), m.end(), method))
    if not hits: return None, t
    hits.sort()
    method = hits[0][2]
    out = t
    for s, e, _ in sorted(hits, reverse=True): out = out[:s] + ' ' + out[e:]
    return method, re.sub(r'[ \t]+', ' ', out).strip()
