"""สกุลเงินต่างประเทศ: ตารางสกุลเงิน + อัตราแลกเปลี่ยนเป็นบาท (แคชในฐานข้อมูล)

แหล่งข้อมูล (ฟรี ไม่ต้องมี API key): Frankfurter (อัตราอ้างอิง ECB ประกาศวันละครั้งในวันทำการ) → สำรอง open.er-api.com
ถ้าเรียกไม่ได้จะใช้เรทที่แคชไว้ล่าสุด (ติดธง stale) — อัตรานี้เป็นเรทอ้างอิง ไม่ใช่เรทบัตร/ร้านแลกเงิน จึงให้ผู้ใช้ใส่เรทเองได้
"""
import re
from datetime import datetime
from zoneinfo import ZoneInfo
import requests
import database as db

TZ = ZoneInfo('Asia/Bangkok')
CACHE_FRESH_SECONDS = 3 * 3600

CURRENCIES = {
    'JPY': {'name': 'เยน', 'sym': '¥', 'dec': 0, 'words': ['เยน', 'yen', 'jpy', '¥', '￥', '円'], 'country': ['ญี่ปุ่น', 'japan']},
    'USD': {'name': 'ดอลลาร์', 'sym': '$', 'dec': 2, 'words': ['ดอลลาร์', 'ดอลล่าร์', 'usd', '$'], 'country': ['อเมริกา', 'สหรัฐ', 'usa']},
    'EUR': {'name': 'ยูโร', 'sym': '€', 'dec': 2, 'words': ['ยูโร', 'euro', 'eur', '€'], 'country': ['ยุโรป', 'europe']},
    'KRW': {'name': 'วอน', 'sym': '₩', 'dec': 0, 'words': ['วอน', 'krw', '₩'], 'country': ['เกาหลี', 'korea']},
    'CNY': {'name': 'หยวน', 'sym': 'CN¥', 'dec': 2, 'words': ['หยวน', 'cny', 'rmb'], 'country': ['จีน', 'china']},
    'GBP': {'name': 'ปอนด์', 'sym': '£', 'dec': 2, 'words': ['ปอนด์', 'gbp', '£'], 'country': ['อังกฤษ', 'england']},
    'SGD': {'name': 'ดอลลาร์สิงคโปร์', 'sym': 'S$', 'dec': 2, 'words': ['ดอลลาร์สิงคโปร์', 'sgd'], 'country': ['สิงคโปร์', 'singapore']},
    'HKD': {'name': 'ดอลลาร์ฮ่องกง', 'sym': 'HK$', 'dec': 2, 'words': ['ดอลลาร์ฮ่องกง', 'hkd'], 'country': ['ฮ่องกง']},
    'TWD': {'name': 'ดอลลาร์ไต้หวัน', 'sym': 'NT$', 'dec': 0, 'words': ['ดอลลาร์ไต้หวัน', 'ntd', 'twd'], 'country': ['ไต้หวัน', 'taiwan']},
}
# สัญลักษณ์นำหน้าตัวเลข (¥1500) — ¥ ถือเป็นเยน
SYMBOLS = {'¥': 'JPY', '￥': 'JPY', '₩': 'KRW', '€': 'EUR', '£': 'GBP', '$': 'USD'}

_WORD_TO_CUR = {}
for _c, _v in CURRENCIES.items():
    for _w in _v['words']: _WORD_TO_CUR[_w.lower()] = _c
_COUNTRY_TO_CUR = {w: c for c, v in CURRENCIES.items() for w in v['country']}


def unit_regex():
    """regex ของคำบอกหน่วยเงิน (เรียงยาว→สั้น เพื่อให้ ดอลลาร์สิงคโปร์ ชนะ ดอลลาร์)"""
    return '|'.join(re.escape(w) for w in sorted(_WORD_TO_CUR, key=len, reverse=True))


def cur_from_word(w):
    return _WORD_TO_CUR.get((w or '').lower())


def find_currency_in(text, include_countries=True):
    """หาสกุลเงินจากคำ/ชื่อประเทศในข้อความ → (cur, start, end, คำที่เจอ) ตัวที่อยู่ก่อนสุด หรือ None"""
    best = None
    table = dict(_WORD_TO_CUR)
    if include_countries: table.update(_COUNTRY_TO_CUR)
    for w, c in table.items():
        pat = re.escape(w) if re.search(r'[\u0e00-\u0e7f]|[^\x00-\x7f]', w) else r'(?<![a-z])' + re.escape(w) + r'(?![a-z])'
        m = re.search(pat, text, re.I)
        if m and (best is None or (m.start(), -len(w)) < (best[1], -(best[2] - best[1]))): best = (c, m.start(), m.end(), w)
    return best


def fmt(cur, amount):
    v = CURRENCIES.get(cur, {'sym': cur + ' ', 'dec': 2})
    if cur == 'THB': return f'฿{float(amount):,.2f}'.replace('.00', '') if float(amount) == int(float(amount)) else f'฿{float(amount):,.2f}'
    return f"{v['sym']}{float(amount):,.{v['dec']}f}"


def cur_name(cur): return CURRENCIES.get(cur, {}).get('name', cur)


# ---------- ดึงอัตรา ----------
_get = requests.get   # ทดสอบแทนที่ได้


def _parse_frankfurter(data, quote):
    """รองรับทั้งรูปแบบเดิม {rates:{THB:x}, date} และแบบรายการ [{date,base,quote,rate}]"""
    if isinstance(data, dict) and isinstance(data.get('rates'), dict) and quote in data['rates']:
        return float(data['rates'][quote]), str(data.get('date') or '')[:10]
    rows = data if isinstance(data, list) else [data] if isinstance(data, dict) else []
    for r in rows:
        if isinstance(r, dict) and r.get('quote') == quote and r.get('rate') is not None:
            return float(r['rate']), str(r.get('date') or '')[:10]
    return None


def _fetch_frankfurter(base, quote, on_date=None):
    seg = on_date or 'latest'
    for url, params in ((f'https://api.frankfurter.dev/v1/{seg}', {'base': base, 'symbols': quote}),
                        (f'https://api.frankfurter.app/{seg}', {'from': base, 'to': quote})):
        try:
            r = _get(url, params=params, timeout=6)
            if r.status_code < 300:
                got = _parse_frankfurter(r.json(), quote)
                if got: return got[0], 'ECB', got[1]
        except Exception as e:
            print('fx frankfurter error:', repr(e)[:120])
    return None


def _fetch_er_api(base, quote):
    try:
        r = _get(f'https://open.er-api.com/v6/latest/{base}', timeout=6)
        if r.status_code < 300:
            j = r.json()
            if j.get('result') == 'success' and quote in (j.get('rates') or {}):
                return float(j['rates'][quote]), 'open.er-api.com', datetime.now(TZ).date().isoformat()
    except Exception as e:
        print('fx er-api error:', repr(e)[:120])
    return None


def _fetch(base, quote, on_date=None):
    got = _fetch_frankfurter(base, quote, on_date) or (_fetch_er_api(base, quote) if not on_date else None)
    if got and 0 < got[0] < 100000: return got
    return None


def _fresh(fetched_at):
    try: return (datetime.now(TZ) - datetime.fromisoformat(str(fetched_at))).total_seconds() < CACHE_FRESH_SECONDS
    except Exception: return False


def _res(hit, stale):
    src, _, d = str(hit.get('source') or '').partition(':')
    return {'rate': float(hit['rate']), 'date': d or hit.get('date'), 'source': src or 'cache', 'stale': bool(stale)}


def get_rate(cur, on_date=None):
    """บาทต่อ 1 หน่วยเงิน cur → {'rate','date','source','stale'} หรือ None ถ้าไม่มีทั้งเรทสดและแคช"""
    cur = (cur or '').upper()
    if cur == 'THB': return {'rate': 1.0, 'date': None, 'source': '', 'stale': False}
    pair = f'{cur}/THB'; today = datetime.now(TZ).date().isoformat(); d = str(on_date)[:10] if on_date else today
    hit = None
    try: hit = db.fx_cache_get(pair, d)
    except Exception as e: print('fx cache error:', repr(e)[:100])
    if hit and (d < today or _fresh(hit['fetched_at'])): return _res(hit, False)
    got = _fetch(cur, 'THB', None if d == today else d)
    if got:
        try: db.fx_cache_put(pair, d, got[0], f'{got[1]}:{got[2]}')
        except Exception as e: print('fx cache put error:', repr(e)[:100])
        return {'rate': got[0], 'date': got[2], 'source': got[1], 'stale': False}
    if hit: return _res(hit, True)
    try: last = db.fx_cache_latest(pair)
    except Exception: last = None
    return _res(last, True) if last else None
