import re
from datetime import datetime

CATS=['อาหาร','บ้าน','เดินทาง','ช้อปปิ้ง','บิล/ค่าสาธารณูปโภค','สุขภาพ','บันเทิง','ท่องเที่ยว','เงินออม/ลงทุน','เงินเดือน','ธุรกิจ','อื่นๆ']

KEYWORDS={
    'อาหาร':['ข้าว','กิน','อาหาร','กาแฟ','กาแฟ','ชา','ชาบู','หมูกระทะ','ร้านอาหาร','ของกิน','ขนม','น้ำ','เครื่องดื่ม','7-11','เซเว่น'],
    'บ้าน':['ค่าเช่า','คอนโด','บ้าน','เฟอร์นิเจอร์','ของใช้บ้าน','ของเข้าบ้าน'],
    'เดินทาง':['น้ำมัน','เติมน้ำมัน','แท็กซี่','grab','bolt','รถไฟ','mrt','bts','ทางด่วน','ที่จอดรถ','เดินทาง'],
    'ช้อปปิ้ง':['ซื้อ','ช้อป','เสื้อ','รองเท้า','กระเป๋า','เครื่องสำอาง','ของใช้'],
    'บิล/ค่าสาธารณูปโภค':['ค่าไฟ','ค่าน้ำ','ค่าเน็ต','อินเทอร์เน็ต','โทรศัพท์','ค่าโทร','บิล'],
    'สุขภาพ':['ยา','หมอ','โรงพยาบาล','คลินิก','สุขภาพ'],
    'บันเทิง':['หนัง','เกม','คอนเสิร์ต','เที่ยวเล่น','karaoke','คาราโอเกะ'],
    'ท่องเที่ยว':['โรงแรม','ที่พัก','เที่ยว','ตั๋วเครื่องบิน','เครื่องบิน'],
    'เงินออม/ลงทุน':['ออม','เก็บเงิน','ลงทุน','กองทุน','หุ้น'],
    'ธุรกิจ':['วัตถุดิบ','แพ็กเกจ','ค่าส่ง','ธุรกิจ','ร้านค้า'],
}

def amount_from_text(text):
    # Prefer a number that looks like a baht amount, including commas/decimals.
    nums=re.findall(r'(?<!\d)(\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)(?!\d)', text)
    if not nums: return None
    vals=[float(x.replace(',','')) for x in nums]
    # Ignore obvious dates/years when another plausible amount exists.
    plausible=[v for v in vals if v < 10000000 and not (1900 <= v <= 2100)]
    return plausible[-1] if plausible else vals[-1]

def category_for(text, tx_type):
    low=text.lower()
    if tx_type=='income':
        if any(k in low for k in ['เงินเดือน','salary','ค่าจ้าง','รายได้','โบนัส']): return 'เงินเดือน'
        return 'อื่นๆ'
    best, best_len = 'อื่นๆ', 0     # เลือกหมวดที่ตรงกับคำ "ยาวที่สุด" เช่น ค่าน้ำ(บิล) ชนะ น้ำ(อาหาร), น้ำมัน(เดินทาง) ชนะ น้ำ
    for cat, kws in KEYWORDS.items():
        for k in kws:
            if k.lower() in low and len(k) > best_len: best, best_len = cat, len(k)
    return best

def parse_text(text, today=None):
    low=text.lower().strip()
    income=bool(re.search(r'เงินเดือน|เงินเข้า|รายรับ|รายได้|รับเงิน|โบนัส|salary|income', low))
    tx_type='income' if income else 'expense'
    amount=amount_from_text(text)
    # Simple date support: today / yesterday. Full natural-language dates stay manual in Free edition.
    occurred_at=today or datetime.now().date().isoformat()
    if 'เมื่อวาน' in text:
        try:
            from datetime import date,timedelta
            occurred_at=(date.fromisoformat(occurred_at)-timedelta(days=1)).isoformat()
        except Exception: pass
    merchant=''
    note=text.strip()
    return {'type':tx_type,'amount':amount,'category':category_for(text,tx_type),'merchant':merchant,'note':note,'occurred_at':occurred_at}

# ---------- อ่านสลิปด้วย AI (เปิดใช้เมื่อตั้ง ANTHROPIC_API_KEY — ถ้าไม่ตั้ง ใช้โหมดฟรีเดิม: ให้พิมพ์ยอดเอง) ----------
import os, json, base64
from datetime import date, timedelta

SLIP_PROMPT = """This is an image sent by a user in Thailand. Decide whether it is a bank transfer / payment slip
(Thai mobile banking, PromptPay, QR payment, e-wallet receipt) and extract data.
Reply with ONLY one JSON object, no markdown, with these keys:
{"is_slip": true|false,
 "amount": number or null,        // the transferred/paid amount only. NOT the fee, NOT the account balance, NOT account numbers. Plain number, no commas.
 "date": "YYYY-MM-DD" or null,    // transaction date in the Christian era. Thai slips use Buddhist era (e.g. 2569 or short '69' = 2026): subtract 543.
 "receiver": string,              // receiving person/shop name as printed, else ""
 "bank": string,                  // bank or app name, else ""
 "memo": string}                  // memo/note field if present, else ""
If you are not sure about the amount, set amount to null. Never guess."""


def _gemini_key(): return os.getenv('GEMINI_API_KEY', '').strip()
def _anthropic_key(): return os.getenv('ANTHROPIC_API_KEY', '').strip()


def slip_providers():
    """ลำดับผู้ให้บริการที่จะลองอ่านสลิป — SLIP_PROVIDER=auto|gemini|anthropic (auto = Gemini ก่อน ถ้าล้มเหลวค่อย Anthropic)"""
    pref = os.getenv('SLIP_PROVIDER', 'auto').strip().lower()
    avail = [n for n, k in (('gemini', _gemini_key()), ('anthropic', _anthropic_key())) if k]
    return [pref] if pref in avail else avail if pref == 'auto' else []


def slip_enabled():
    return bool(slip_providers())


def _media_type(b):
    if b[:3] == b'\xff\xd8\xff': return 'image/jpeg'
    if b[:8] == b'\x89PNG\r\n\x1a\n': return 'image/png'
    if b[:4] == b'RIFF' and b[8:12] == b'WEBP': return 'image/webp'
    if b[:3] == b'GIF': return 'image/gif'
    return 'image/jpeg'


def _extract_json(text):
    m = re.search(r'\{.*\}', text or '', re.S)
    if not m: return None
    try: return json.loads(m.group(0))
    except ValueError: return None


def _empty_slip(today=None):
    return {'type': 'expense', 'amount': None, 'category': 'อื่นๆ', 'merchant': '', 'note': '',
            'occurred_at': today or datetime.now().date().isoformat()}


def slip_from_json(data, today=None):
    """แปลง JSON ที่ AI อ่านได้เป็นรายการ พร้อมตรวจความสมเหตุสมผล (ยอด/วันที่) — ไม่ผ่านจะได้ amount=None"""
    today = today or datetime.now().date().isoformat()
    out = _empty_slip(today)
    if not isinstance(data, dict) or not data.get('is_slip'): return out
    try: amount = float(str(data.get('amount')).replace(',', ''))
    except (TypeError, ValueError): return out
    if not (0 < amount < 10000000): return out
    d = str(data.get('date') or '')[:10]
    try:
        y, mth, dd = (int(x) for x in d.split('-'))
        if y > 2400: y -= 543                                   # พ.ศ. → ค.ศ.
        slip_date = date(y, mth, dd)
        t = date.fromisoformat(today)
        if not (t - timedelta(days=730) <= slip_date <= t + timedelta(days=1)): slip_date = t
        d = slip_date.isoformat()
    except (ValueError, TypeError):
        d = today
    receiver = str(data.get('receiver') or '').strip()[:60]
    bank = str(data.get('bank') or '').strip()[:30]
    memo = str(data.get('memo') or '').strip()[:80]
    note = ' · '.join(x for x in (f'สลิป {bank}'.strip(), receiver, memo) if x and x != 'สลิป')
    out.update({'amount': round(amount, 2), 'merchant': receiver, 'note': note or 'สลิปโอนเงิน',
                'category': category_for(memo, 'expense') if memo else 'อื่นๆ', 'occurred_at': d})   # ไม่เดาจากชื่อผู้รับ (เช่น สมชาย มีคำว่า "ชา")
    return out


def _call_gemini(content):
    """คืน dict ที่ AI อ่านได้ (อาจเป็น {} ถ้าไม่ใช่สลิป) หรือ None ถ้าเรียก API ไม่สำเร็จ"""
    import requests
    model = os.getenv('GEMINI_MODEL', 'gemini-3.8-flash').strip()
    r = requests.post(f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent',
        headers={'x-goog-api-key': _gemini_key(), 'Content-Type': 'application/json'},
        json={'contents': [{'parts': [
                  {'inline_data': {'mime_type': _media_type(content), 'data': base64.b64encode(content).decode()}},
                  {'text': SLIP_PROMPT}]}],
              'generationConfig': {'temperature': 0, 'responseMimeType': 'application/json'}},
        timeout=45)
    if r.status_code >= 300:
        print('slip gemini error:', r.status_code, r.text[:200]); return None
    cands = r.json().get('candidates') or []
    if not cands:
        print('slip gemini: no candidates (blocked?)'); return None
    text = ''.join(p.get('text', '') for p in (cands[0].get('content') or {}).get('parts', []))
    return _extract_json(text) or {}


def _call_anthropic(content):
    import requests
    r = requests.post('https://api.anthropic.com/v1/messages',
        headers={'x-api-key': _anthropic_key(), 'anthropic-version': '2023-06-01', 'content-type': 'application/json'},
        json={'model': os.getenv('SLIP_MODEL', 'claude-haiku-5-5'), 'max_tokens': 400,
              'messages': [{'role': 'user', 'content': [
                  {'type': 'image', 'source': {'type': 'base64', 'media_type': _media_type(content), 'data': base64.b64encode(content).decode()}},
                  {'type': 'text', 'text': SLIP_PROMPT}]}]},
        timeout=45)
    if r.status_code >= 300:
        print('slip anthropic error:', r.status_code, r.text[:200]); return None
    text = ''.join(b.get('text', '') for b in r.json().get('content', []) if b.get('type') == 'text')
    return _extract_json(text) or {}


def parse_slip(content: bytes):
    """อ่านสลิป: ลองผู้ให้บริการตามลำดับ — ถ้าเรียก API ล้มเหลว (โควตาหมด/เน็ต/ถูกบล็อก) ค่อยลองเจ้าถัดไป
    ถ้าเรียกสำเร็จแต่ไม่ใช่สลิป/อ่านไม่ออก จะหยุดเลย (ไม่เสียเงินเจ้าที่สองซ้ำ)"""
    today = datetime.now().date().isoformat()
    if not content: return _empty_slip(today)
    for name in slip_providers():
        try:
            data = {'gemini': _call_gemini, 'anthropic': _call_anthropic}[name](content)
        except Exception as e:
            print('slip error:', name, repr(e)); data = None
        if data is not None:
            return slip_from_json(data, today)
    return _empty_slip(today)
