"""โหมดทริป + ตัวแปลงเงิน + บันทึกรายจ่ายเป็นเงินต่างประเทศ

  1000 เยน กี่บาท / 5000 บาท กี่เยน / เรทเยน
  เริ่มทริปญี่ปุ่น [ชื่อ] [7 วัน] / จบทริป / ทริป / สรุปทริป / ตั้งเรททริป 0.23 / ทริปทั้งหมด
  ราเมง 1000 เยน [เรท 0.23]   (หรือในโหมดทริป พิมพ์ ราเมง 1000 ได้เลย — พิมพ์ "บาท" ต่อท้ายถ้าจ่ายเป็นบาท)

classify() ไม่แตะฐานข้อมูล/เน็ต; run() และ prepare_entry() อาจเรียกเน็ต → เรียกผ่าน asyncio.to_thread
"""
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import database as db
import fx
from ai import parse_text

TZ = ZoneInfo('Asia/Bangkok')
_MONTHS = ['ม.ค.', 'ก.พ.', 'มี.ค.', 'เม.ย.', 'พ.ค.', 'มิ.ย.', 'ก.ค.', 'ส.ค.', 'ก.ย.', 'ต.ค.', 'พ.ย.', 'ธ.ค.']
_NUM = r'(\d[\d,]*(?:\.\d+)?)'
_TAIL = r'(?:ไหม|หรอ|เหรอ|ครับ|ค่ะ|คะ|นะ|\?)*'
_SEP = r'(?:=|เท่ากับ|แลกเป็น|แลก|เป็น|คือ|ได้กี่|ได้|กี่)'


def _ds(iso):
    d = datetime.fromisoformat(str(iso)[:10]); return f'{d.day} {_MONTHS[d.month - 1]}'


def _f(x): return float(str(x).replace(',', ''))


# ---------- จัดประเภทข้อความ ----------
def classify(text):
    t = (text or '').strip()
    if not t or len(t) > 80: return None
    tn = t.replace(' ', '').lower()
    U = fx.unit_regex()
    # แปลงเป็นบาท: 1000 เยน กี่บาท / ¥1000 เป็นบาท
    m = re.match(rf'^(?:(¥|￥|₩|€|£|\$))?{_NUM}({U})?{_SEP}+(?:กี่)?บาท(?:ไทย)?{_TAIL}$', tn)
    if m and (m.group(1) or m.group(3)):
        cur = fx.SYMBOLS.get(m.group(1)) if m.group(1) else fx.cur_from_word(m.group(3))
        if cur: return ('conv', {'amount': _f(m.group(2)), 'cur': cur, 'dir': 'to_thb'})
    # แปลงจากบาท: 5000 บาท กี่เยน
    m = re.match(rf'^{_NUM}บาท(?:ไทย)?{_SEP}+({U}){_TAIL}$', tn)
    if m and fx.cur_from_word(m.group(2)): return ('conv', {'amount': _f(m.group(1)), 'cur': fx.cur_from_word(m.group(2)), 'dir': 'from_thb'})
    # เรท: เรทเยน / เยนวันนี้ / ค่าเงินเยน / เยนเท่าไหร่
    allw = '|'.join(re.escape(w) for w in sorted(set(list(fx._WORD_TO_CUR) + list(fx._COUNTRY_TO_CUR)), key=len, reverse=True))
    m = re.match(rf'^(?:(?:เรท|อัตรา(?:แลกเปลี่ยน)?|ค่าเงิน)({allw})(?:วันนี้|ตอนนี้)?(?:เท่าไหร่|เท่าไร)?|({allw})(?:วันนี้|ตอนนี้|เท่าไหร่|เท่าไร)){_TAIL}$', tn)
    if m:
        w = m.group(1) or m.group(2)
        cur = fx.cur_from_word(w) or fx._COUNTRY_TO_CUR.get(w)
        if cur: return ('rate', {'cur': cur})
    # ---- ทริป ----
    if re.match(r'^(จบทริป|ปิดทริป|กลับบ้านแล้ว|กลับไทยแล้ว)$', tn): return ('trip_end', {})
    if tn in ('ทริป', 'ทริปของฉัน', 'ทริปตอนนี้'): return ('trip_info', {})
    if tn in ('ทริปทั้งหมด', 'ประวัติทริป', 'ทริปที่ผ่านมา'): return ('trip_list', {})
    if tn.startswith('สรุปทริป'): return ('trip_summary', {})
    m = re.match(r'^ตั้งเรททริป\s*(?:เป็น)?\s*(\d+(?:\.\d+)?)$', t) or re.match(r'^ตั้งเรททริป(\d+(?:\.\d+)?)$', tn)
    if m: return ('trip_rate', {'rate': float(m.group(1))})
    if re.match(r'^ตั้งเรททริป\s*(อัตโนมัติ|ตลาด|auto)$', t, re.I): return ('trip_rate', {'rate': None})
    if t.startswith('เริ่มทริป'):
        rest = t[len('เริ่มทริป'):].strip()
        days = 14
        dm = re.search(r'(\d+)\s*วัน', rest)
        if dm: days = int(dm.group(1)); rest = (rest[:dm.start()] + rest[dm.end():]).strip()
        rest = re.sub(r'^ไป\s*', '', rest)
        found = fx.find_currency_in(rest, include_countries=True)
        if not found: return ('trip_start', {'error': 'ทริปไปประเทศไหนครับ 🌏\nเช่น “เริ่มทริปญี่ปุ่น” หรือ “เริ่มทริปเกาหลี 7 วัน”\nรองรับ: ญี่ปุ่น เกาหลี อเมริกา ยุโรป จีน อังกฤษ สิงคโปร์ ฮ่องกง ไต้หวัน'})
        cur, a, b, word = found
        name = (rest[:a] + rest[b:]).strip(' -–—:')
        return ('trip_start', {'cur': cur, 'days': max(1, min(days, 90)), 'name': name or f'ทริป{word if word in fx._COUNTRY_TO_CUR else fx.cur_name(cur)}'})
    return None


# ---------- บันทึกรายจ่ายเป็นเงินต่างประเทศ ----------
def _find_explicit(text):
    """หา '1000 เยน' หรือ '¥1000' ในข้อความ → (cur, amount, start, end) ตัวแรก"""
    U = fx.unit_regex()
    cands = []
    m = re.search(rf'{_NUM}\s*({U})(?![A-Za-z\u0e00-\u0e7f])', text, re.I)
    if m and fx.cur_from_word(m.group(2)): cands.append((m.start(), m.end(), fx.cur_from_word(m.group(2)), _f(m.group(1))))
    m = re.search(rf'(¥|￥|₩|€|£|\$)\s*{_NUM}', text)
    if m: cands.append((m.start(), m.end(), fx.SYMBOLS[m.group(1)], _f(m.group(2))))
    if not cands: return None
    s, e, cur, amt = min(cands)
    return cur, amt, s, e


def _trip_footer(trip, today):
    if not trip: return ''
    d = (datetime.fromisoformat(today) - datetime.fromisoformat(str(trip['start_date'])[:10])).days + 1
    total = (datetime.fromisoformat(str(trip['end_date'])[:10]) - datetime.fromisoformat(str(trip['start_date'])[:10])).days + 1
    return f"\n✈️ {trip['name']} · วันที่ {d}/{total} · พิมพ์ “บาท” ต่อท้ายถ้าจ่ายเป็นบาท · “จบทริป” เมื่อกลับ"


def prepare_entry(text, user_id, today=None):
    """ถ้าข้อความเป็นรายจ่ายเงินต่างประเทศ (ระบุหน่วยเอง หรืออยู่ในโหมดทริป) → คืน dict สำหรับ app:
       {'text': ข้อความสำหรับ parse_text, 'thb', 'fields': {currency,original_amount,fx_rate,trip_id}, 'notice'} หรือ {'error'}; ไม่ใช่ → None"""
    today = today or datetime.now(TZ).date().isoformat()
    rate_m = re.search(r'(?:เรท|rate|@)\s*(\d+(?:\.\d+)?)', text, re.I)
    clean = (text[:rate_m.start()] + text[rate_m.end():]).strip() if rate_m else text    # ตัดข้อความ "เรท 0.23" ออกก่อนหายอด
    explicit = _find_explicit(clean)
    trip = db.get_active_trip(user_id, today)
    if explicit:
        cur, orig, s, e = explicit
    else:
        if not trip or re.search(r'บาท|฿|thb', clean, re.I): return None
        p = parse_text(clean, today)
        if not p.get('amount'): return None
        cur, orig = trip['currency'], float(p['amount'])
    if rate_m:
        rate, src, stale = float(rate_m.group(1)), 'เรทที่คุณระบุ', False
    elif trip and trip.get('fixed_rate') and cur == trip['currency']:
        rate, src, stale = float(trip['fixed_rate']), 'เรทของทริป', False
    else:
        info = fx.get_rate(cur)
        if not info:
            return {'error': f"ดึงเรท{fx.cur_name(cur)}ไม่ได้ตอนนี้ 🙏\nใส่เรทเองได้ เช่น “ราเมง 1000 เยน เรท 0.23” หรือพิมพ์ยอดเป็นบาทแทน"}
        rate, stale = info['rate'], info['stale']
        src = f"เรท {info['source']} {_ds(info['date'])}" if info.get('date') else 'เรทตลาด'
    if not (0 < rate < 100000) or not (0 < orig < 1e9): return {'error': 'ยอดหรือเรทไม่ถูกต้องครับ'}
    thb = round(orig * rate, 2)
    parse_src = f'{clean[:s]}{thb:.2f} บาท{clean[e:]}'.strip() if explicit else clean
    notice = f'💱 {fx.fmt(cur, orig)} × {rate:.4f} = ฿{thb:,.2f}\n{src}'
    if stale: notice += '\n⚠️ ดึงเรทล่าสุดไม่ได้ ใช้เรทที่เก็บไว้ ถ้าไม่ตรง แก้ด้วย “แก้ล่าสุด เรท 0.23”'
    else: notice += ' · แก้เรทได้ด้วย “แก้ล่าสุด เรท 0.23”'
    notice += _trip_footer(trip, today)
    return {'text': parse_src, 'thb': thb, 'notice': notice,
            'fields': {'currency': cur, 'original_amount': orig, 'fx_rate': rate, 'trip_id': trip['id'] if trip else None}}


# ---------- ตอบคำสั่ง ----------
def _summary_text(sm, today):
    t = sm['trip']; cur = t['currency']
    head = f"✈️ {t['name']} ({_ds(t['start_date'])} – {_ds(t['end_date'])}){'' if not t['active'] else ' · กำลังเดินทาง'}"
    if not sm['count']: return head + '\nยังไม่มีรายจ่ายในทริปนี้ครับ'
    lines = [head, f"ใช้ไป {fx.fmt(cur, sm['total_foreign'])} ≈ ฿{sm['total_thb']:,.0f} · {sm['count']} รายการ"]
    for c in sm['categories'][:4]:
        lines.append(f"• {c['category']} ฿{c['thb']:,.0f}" + (f" ({fx.fmt(cur, c['foreign'])})" if c['foreign'] else ''))
    lines.append(f"เฉลี่ยวันละ ฿{sm['per_day_thb']:,.0f} ({sm['days']} วัน)")
    if sm['avg_rate']: lines.append(f"เรทเฉลี่ยที่ใช้ {sm['avg_rate']:.4f}")
    return '\n'.join(lines)


def run(kind, p, user_id, h=None, hid=None, today=None):
    today = today or datetime.now(TZ).date().isoformat()
    if kind == 'conv':
        info = fx.get_rate(p['cur'])
        if not info: return f"ดึงเรท{fx.cur_name(p['cur'])}ไม่ได้ตอนนี้ 🙏 ลองใหม่อีกครั้งนะครับ"
        r = info['rate']
        out = (f"💱 {fx.fmt(p['cur'], p['amount'])} ≈ ฿{p['amount'] * r:,.2f}" if p['dir'] == 'to_thb'
               else f"💱 ฿{p['amount']:,.2f} ≈ {fx.fmt(p['cur'], p['amount'] / r)}")
        out += f"\n1 {fx.cur_name(p['cur'])} = {r:.4f} บาท · {info['source']}" + (f" {_ds(info['date'])}" if info.get('date') else '')
        if info['stale']: out += '\n⚠️ ดึงเรทล่าสุดไม่ได้ ใช้เรทที่เก็บไว้'
        return out + '\nเรทอ้างอิง ไม่ใช่เรทบัตร/ร้านแลกเงิน (ของจริงต่างเล็กน้อย)'
    if kind == 'rate':
        info = fx.get_rate(p['cur'])
        if not info: return f"ดึงเรท{fx.cur_name(p['cur'])}ไม่ได้ตอนนี้ 🙏"
        r = info['rate']; n = fx.cur_name(p['cur'])
        return (f"💱 เรท{n}\n1 {n} = {r:.4f} บาท\n{'100' if r < 1 else '1'} {n} = {r * (100 if r < 1 else 1):,.2f} บาท · 1 บาท = {1 / r:,.{2 if r > 0.05 else 1}f} {n}\n{info['source']}"
                + (f" {_ds(info['date'])}" if info.get('date') else '') + ('\n⚠️ ใช้เรทที่เก็บไว้ (ดึงเรทใหม่ไม่ได้)' if info['stale'] else ''))
    if kind == 'trip_start':
        if p.get('error'): return p['error']
        t, prev = db.start_trip(user_id, hid, p['name'], p['cur'], p['days'], today)
        info = fx.get_rate(p['cur'])
        rate_line = (f"เรทวันนี้: 1 {fx.cur_name(p['cur'])} = {info['rate']:.4f} บาท ({info['source']})" if info
                     else f"⚠️ ดึงเรทไม่ได้ตอนนี้ ตั้งเรทเองด้วย “ตั้งเรททริป 0.23”")
        return (f"✈️ เริ่ม{t['name']}แล้ว\nสกุลเงิน: {fx.cur_name(p['cur'])} ({p['cur']}) · ถึง {_ds(t['end_date'])} ({p['days']} วัน)\n{rate_line}\n\n"
                f"ตอนนี้พิมพ์ “ราเมง 1000” จะนับเป็น{fx.cur_name(p['cur'])} แล้วแปลงเป็นบาทให้เอง\n"
                f"• จ่ายเป็นบาทให้พิมพ์ “บาท” ต่อท้าย เช่น “แท็กซี่ 300 บาท”\n• เรทที่แลกจริง: “ตั้งเรททริป 0.23” (ปรับรายการเดิมให้ด้วย)\n• จบทริป: “จบทริป” (ปิดเองเมื่อครบวัน)"
                + (f"\n\n(ปิดทริปเดิม “{prev['name']}” ให้แล้ว)" if prev else ''))
    if kind == 'trip_end':
        t = db.end_trip(user_id, today)
        if not t: return 'ตอนนี้ไม่ได้อยู่ในโหมดทริปครับ'
        return '🏁 จบทริปแล้ว กลับมาใช้บาทตามปกติ\n\n' + _summary_text(db.trip_summary(t, today), today)
    if kind == 'trip_info':
        t = db.get_active_trip(user_id, today)
        if not t: return 'ยังไม่ได้อยู่ในโหมดทริปครับ ✈️\nพิมพ์ “เริ่มทริปญี่ปุ่น” เพื่อเริ่ม (พิมพ์ “สรุปทริป” ดูทริปล่าสุด)'
        return _summary_text(db.trip_summary(t, today), today) + (f"\nเรทคงที่: {t['fixed_rate']:.4f}" if t.get('fixed_rate') else '\nเรท: ตลาดรายวัน') + _trip_footer(t, today)
    if kind == 'trip_summary':
        t = db.get_active_trip(user_id, today) or next(iter(db.list_trips(user_id, 1)), None)
        if not t: return 'ยังไม่มีทริปครับ พิมพ์ “เริ่มทริปญี่ปุ่น” เพื่อเริ่ม ✈️'
        return _summary_text(db.trip_summary(t, today), today)
    if kind == 'trip_list':
        ts = db.list_trips(user_id, 10)
        if not ts: return 'ยังไม่มีทริปครับ'
        return '✈️ ทริปของคุณ\n' + '\n'.join(f"• {t['name']} ({_ds(t['start_date'])}–{_ds(t['end_date'])}){' · กำลังเดินทาง' if t['active'] else ''}" for t in ts)
    if kind == 'trip_rate':
        t, n = db.set_trip_rate(user_id, p['rate'], today)
        if not t: return 'ต้องอยู่ในโหมดทริปก่อนครับ พิมพ์ “เริ่มทริปญี่ปุ่น”'
        if p['rate'] is None: return '💱 กลับไปใช้เรทตลาดรายวันแล้ว (รายการเดิมไม่เปลี่ยน)'
        return f"💱 ตั้งเรททริป 1 {fx.cur_name(t['currency'])} = {p['rate']:.4f} บาท แล้ว\nปรับรายการเดิมในทริป {n} รายการให้ตรงเรทนี้" + ('' if n else ' (ยังไม่มีรายการ)')
    return None
