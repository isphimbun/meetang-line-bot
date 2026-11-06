"""ถามผ่านแชท + แก้รายการ + สรุปดอกเบี้ยบ้านรายปี (ภาษี)

  เดือนนี้ใช้ไปเท่าไหร่ / ค่ากินเดือนนี้ / สัปดาห์ที่แล้วใช้เท่าไหร่ / วันนี้รายรับเท่าไหร่
  แก้ 123 150 / แก้ล่าสุด 150 หมวด อาหาร
  สรุปดอกเบี้ยบ้าน 2569 หาร 2      (ต้องมีสิทธิ์ loan)

classify(text) เป็นฟังก์ชันล้วน (ไม่แตะฐานข้อมูล) → คืน (kind, params) หรือ None
run(kind, params, user_id, h, hid) → ข้อความตอบกลับ หรือ None ถ้าไม่ควรตอบ (เช่น ไม่มีสิทธิ์)
"""
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import database as db
from ai import CATS, category_for

TZ = ZoneInfo('Asia/Bangkok')
_MONTHS = ['ม.ค.', 'ก.พ.', 'มี.ค.', 'เม.ย.', 'พ.ค.', 'มิ.ย.', 'ก.ค.', 'ส.ค.', 'ก.ย.', 'ต.ค.', 'พ.ย.', 'ธ.ค.']

# (ชื่อช่วง, regex) เรียงจากเฉพาะเจาะจงไปกว้าง
_PERIODS = [('last_month', r'เดือนที่แล้ว|เดือนก่อน'), ('last_week', r'(สัปดาห์|อาทิตย์)ที่แล้ว|(สัปดาห์|อาทิตย์)ก่อน'),
            ('week', r'สัปดาห์นี้|อาทิตย์นี้'), ('month', r'เดือนนี้'), ('yesterday', r'เมื่อวาน'),
            ('today', r'วันนี้'), ('year', r'ปีนี้')]
_LABEL = {'today': 'วันนี้', 'yesterday': 'เมื่อวาน', 'week': 'สัปดาห์นี้', 'last_week': 'สัปดาห์ที่แล้ว',
          'month': 'เดือนนี้', 'last_month': 'เดือนที่แล้ว', 'year': 'ปีนี้'}
_TRIGGER = re.compile(r'ใช้|จ่าย|เท่าไหร่|เท่าไร|เท่าไหร|เท่าใด|รวม|สรุป|หมดไป|กินไป|ซื้อไป|รายรับ|รายได้|เงินเข้า|เหลือ|คงเหลือ')


def _d(x): return f'{x.day} {_MONTHS[x.month - 1]}'


def period_range(name, today):
    if name == 'today': return today, today
    if name == 'yesterday': y = today - timedelta(days=1); return y, y
    if name == 'week': return today - timedelta(days=today.weekday()), today
    if name == 'last_week':
        end = today - timedelta(days=today.weekday() + 1); return end - timedelta(days=6), end
    if name == 'month': return today.replace(day=1), today
    if name == 'last_month':
        end = today.replace(day=1) - timedelta(days=1); return end.replace(day=1), end
    if name == 'year': return today.replace(month=1, day=1), today
    raise ValueError(name)


def _find_category(text):
    """หมวดที่ถูกพูดถึงในประโยค (ชื่อหมวดตรงๆ หรือคำในหมวด เช่น ค่ากิน→อาหาร) ไม่เจอคืน None"""
    for c in CATS:
        if c != 'อื่นๆ' and c in text: return c
    c = category_for(text, 'expense')
    return c if c != 'อื่นๆ' else ('อื่นๆ' if 'อื่นๆ' in text else None)


def classify(text):
    t = (text or '').strip()
    if not t or len(t) > 60: return None
    # --- แก้รายการ ---
    m = re.match(r'^แก้(?:ไข)?\s+(\d+)\s+(.+)$', t)
    last = re.match(r'^แก้(?:ไข)?ล่าสุด\s+(.+)$', t)
    if m or last:
        rest = (m.group(2) if m else last.group(1)).strip()
        cat_m = re.search(r'หมวด\s*(\S+)', rest)
        amt_m = re.search(r'(?<![\d.])(\d[\d,]*(?:\.\d+)?)', re.sub(r'หมวด\s*\S+', '', rest))
        category = None
        if cat_m:
            w = cat_m.group(1); category = w if w in CATS else (category_for(w, 'expense') if category_for(w, 'expense') != 'อื่นๆ' else None)
            if category is None: return ('edit', {'error': f'ไม่รู้จักหมวด “{w}” ลองใช้: ' + ' · '.join(c for c in CATS)})
        amount = float(amt_m.group(1).replace(',', '')) if amt_m else None
        if amount is None and category is None: return None
        return ('edit', {'id': int(m.group(1)) if m else None, 'amount': amount, 'category': category})
    # --- สรุปดอกเบี้ยบ้านรายปี ---
    tl = t.replace(' ', '')
    if (tl.startswith('สรุปดอกเบี้ย') or re.match(r'^ดอกเบี้ย(บ้าน|สินเชื่อ|ภาษี)?(ปี)?(25\d\d|20\d\d)?(หาร\d+|กู้ร่วม\d+)?$', tl)
            or ('ลดหย่อน' in tl and 'ดอกเบี้ย' in tl)):
        y = re.search(r'(25\d\d|20\d\d)', tl)
        n = re.search(r'(?:หาร|กู้ร่วม)(\d+)', tl)
        year = int(y.group(1)) if y else None
        if year and year > 2400: year -= 543
        return ('tax', {'year': year, 'share': max(1, min(int(n.group(1)), 10)) if n else 1})
    # --- ถามยอดใช้จ่าย ---
    if re.search(r'\d', t) or t.startswith(('ลบ', 'แก้')): return None
    period = next((n for n, rx in _PERIODS if re.search(rx, t)), None)
    if not period or not _TRIGGER.search(t): return None
    kind = 'income' if re.search(r'รายรับ|รายได้|เงินเข้า', t) else ('balance' if re.search(r'เหลือ|คงเหลือ', t) else 'expense')
    return ('spend', {'period': period, 'type': kind, 'category': _find_category(t) if kind == 'expense' else None})


def _money(v):
    v = float(v or 0); return f'{v:,.0f}' if abs(v - round(v)) < 0.005 else f'{v:,.2f}'


def _run_spend(p, user_id, hid, today):
    s, e = period_range(p['period'], today)
    rng = _d(s) if s == e else f'{_d(s)} – {_d(e)}'
    label = f"{_LABEL[p['period']]} ({rng})"
    if p['type'] == 'balance':
        inc = db.sum_transactions(s, e, user_id, hid, 'income'); exp = db.sum_transactions(s, e, user_id, hid, 'expense')
        if not inc['count'] and not exp['count']: return f'📊 {label}\nยังไม่มีรายการเลยครับ'
        return f"📊 {label}\nรายรับ {_money(inc['total'])} − รายจ่าย {_money(exp['total'])}\nคงเหลือ {_money(inc['total'] - exp['total'])} บาท"
    r = db.sum_transactions(s, e, user_id, hid, p['type'], p.get('category'))
    what = 'รายรับ' if p['type'] == 'income' else (f"หมวด {p['category']}" if p.get('category') else 'ใช้ไป')
    if not r['count']: return f'📊 {label}\nยังไม่มี{"รายรับ" if p["type"] == "income" else "รายจ่าย"}{" หมวด " + p["category"] if p.get("category") else ""}ครับ'
    lines = [f'📊 {label}', f"{what} {_money(r['total'])} บาท · {r['count']} รายการ"]
    if not p.get('category') and len(r['categories']) > 0:
        lines.append(' · '.join(f"{c['category']} {_money(c['total'])}" for c in r['categories'][:3]))
    days = (e - s).days + 1
    if p['type'] == 'expense' and days > 1: lines.append(f"เฉลี่ยวันละ {_money(r['total'] / days)} บาท")
    if p['period'] == 'month':    # เทียบช่วงเดียวกันของเดือนก่อน
        ps, pe_full = period_range('last_month', today)
        pe = min(pe_full, ps.replace(day=min(today.day, pe_full.day)))
        prev = db.sum_transactions(ps, pe, user_id, hid, p['type'], p.get('category'))
        if prev['count']:
            diff = r['total'] - prev['total']
            lines.append(f"ช่วงเดียวกันเดือนก่อน {_money(prev['total'])} ({'+' if diff >= 0 else '−'}{_money(abs(diff))})")
    return '\n'.join(lines)


def _run_edit(p, user_id, hid):
    if p.get('error'): return p['error']
    tx_id = p.get('id')
    if tx_id is None:
        rows = db.get_recent(1, user_id=user_id, household_id=hid)
        if not rows: return 'ยังไม่มีรายการให้แก้ครับ'
        tx_id = rows[0]['id']
    before = None
    rows = [r for r in db.get_recent(200, user_id=user_id, household_id=hid) if r['id'] == tx_id]
    if rows: before = rows[0]
    row, err = db.update_transaction(tx_id, user_id, hid, amount=p.get('amount'), category=p.get('category'))
    if err: return f'⚠️ {err}'
    parts = []
    if p.get('amount') is not None: parts.append(f"ยอด {_money(before['amount']) if before else '?'} → {_money(row['amount'])} บาท")
    if p.get('category'): parts.append(f"หมวด {before['category'] if before else '?'} → {row['category']}")
    return f"✏️ แก้รายการ #{tx_id} แล้ว ({row.get('merchant') or row.get('note') or row['category']})\n" + '\n'.join(parts)


def _run_tax(p, user_id, hid, today):
    if not hid or not db.user_has_feature(user_id, hid, 'loan'): return None
    m = db.get_mortgage(hid)
    if not m: return 'ยังไม่ได้ตั้งข้อมูลสินเชื่อบ้านใน Dashboard ครับ'
    rows = db.mortgage_interest_by_year(m, today)
    if not rows: return 'ยังไม่มีงวดสินเชื่อที่บันทึกไว้ครับ'
    year = p.get('year') or today.year
    r = next((x for x in rows if x['year'] == year), None)
    if not r: return 'ไม่มีงวดที่บันทึกในปี %d (พ.ศ. %d) ครับ\nปีที่มีข้อมูล: %s' % (year, year + 543, ', '.join(str(x['year'] + 543) for x in rows))
    share = p.get('share', 1)
    mine = round(r['interest'] / share, 2)
    ded = round(min(mine, db.TAX_INTEREST_LIMIT), 2)
    lines = [f"🏠 ดอกเบี้ยบ้านปี {year + 543} (ค.ศ. {year})",
             f"{r['count']} งวด · จ่ายรวม {_money(r['paid'])} บาท",
             f"ดอกเบี้ย {_money(r['interest'])} · เงินต้น {_money(r['principal'] + r['extra'])}"]
    if share > 1: lines.append(f"กู้ร่วม {share} คน → ส่วนของคุณ {_money(mine)} บาท")
    lines.append(f"ลดหย่อนได้ ≈ {_money(ded)} บาท" + (' (ติดเพดาน 100,000 บาท/ปี)' if mine > db.TAX_INTEREST_LIMIT else ''))
    if r.get('projected_interest') and r['projected_interest'] > r['interest']:
        lines.append(f"คาดทั้งปี ≈ {_money(r['projected_interest'])} บาท (รวมงวดที่เหลือ)")
    if r.get('partial_start'): lines.append('⚠️ ปีนี้นับเฉพาะงวดตั้งแต่วันที่ยอดยกมา')
    if r.get('maybe_incomplete'): lines.append('⚠️ จำนวนงวดน้อยกว่าปกติ ตรวจว่าบันทึกครบหรือไม่')
    lines.append('📄 ใช้หนังสือรับรองดอกเบี้ยจากธนาคารเป็นหลักฐาน ตัวเลขนี้คำนวณจากงวดที่บันทึกไว้ อาจต่างเล็กน้อย')
    return '\n'.join(lines)


def run(kind, params, user_id, h, hid, today=None):
    today = today or datetime.now(TZ).date()
    if kind == 'spend': return _run_spend(params, user_id, hid, today)
    if kind == 'edit': return _run_edit(params, user_id, hid)
    if kind == 'tax': return _run_tax(params, user_id, hid, today)
    return None
