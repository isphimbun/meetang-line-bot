"""คำสั่งแชท LINE สำหรับข้อมูลที่เดิมบันทึกได้เฉพาะ Dashboard

  บ้าน ค่าน้ำ 320                  → ค่าใช้จ่ายบ้าน
  จ่ายงวดบ้าน 20000 [โปะ 5000]    → ค่างวดสินเชื่อบ้าน (ยอดรวมที่จ่าย; โปะ = ส่วนที่โปะรวมอยู่ในยอดนั้นแล้ว เหมือน Dashboard)
  ผ่อน เครื่องซักผ้า [1500]        → งวดผ่อน (ไม่ใส่ยอด = ใช้ค่างวดที่ตั้งไว้)
  จ่ายประกัน MRTA [1500]           → งวดประกันแบบผ่อนแยก (ไม่ใส่ยอด = ใช้ค่างวดที่ตั้งไว้)

handle_house_chat() คืนข้อความตอบกลับ หรือ None ถ้าไม่ใช่คำสั่งกลุ่มนี้
สิทธิ์/การคำนวณใช้ฟังก์ชันเดียวกับ Dashboard และแจ้งสมาชิกในบ้านอัตโนมัติ
"""
import re
from database import (get_active_household, user_has_feature, get_mortgage, add_mortgage_payment,
                      add_house_expense, get_installments, add_installment_payment,
                      get_house_insurance, add_house_insurance_payment)
from notify import notify_house_expense, notify_loan_payment, notify_installment_payment, notify_insurance_payment

_NUM = re.compile(r'\d[\d,]*(?:\.\d+)?')

# ใช้ค่าเดียวกับ dropdown ใน Dashboard (มี emoji นำหน้า)
_EXPENSE_TYPES = [  # เรียงจากคำเฉพาะไปคำกว้าง ("ซ่อมก๊อกน้ำ" ต้องเป็นค่าซ่อม ไม่ใช่ค่าน้ำ)
    (('ซ่อม',), '🔧 ค่าซ่อม'), (('ส่วนกลาง',), '🏢 ค่าส่วนกลาง'),
    (('เน็ต', 'อินเทอร์เน็ต', 'internet', 'wifi', 'ไวไฟ', 'ไฟเบอร์'), '📶 อินเทอร์เน็ต'),
    (('น้ำ',), '💧 ค่าน้ำ'), (('ไฟ',), '⚡ ค่าไฟ'),
]
_NO_FEATURE = 'ฟีเจอร์นี้ยังไม่ได้เปิดสิทธิ์ให้บัญชีของคุณครับ 🔒\nให้ Super Admin เปิดสิทธิ์ให้ก่อน'
_NO_HOUSE = '🏠 ยังไม่ได้เลือกบ้านครับ\nพิมพ์ “สร้างบ้าน ชื่อบ้าน” หรือ “เข้าร่วม รหัส” ก่อน'


def _num(s):
    m = _NUM.search(s or '')
    return float(m.group().replace(',', '')) if m else None


def _strip_num(s):
    return _NUM.sub(' ', s or '', count=1).strip()


def _baht(v):
    v = float(v or 0)
    return f'{v:,.0f}' if abs(v - round(v)) < 0.005 else f'{v:,.2f}'


def _pick(rows, query, label_fn, what):
    """เลือกรายการจากชื่อที่พิมพ์ → (row, None) หรือ (None, ข้อความบอกผู้ใช้)"""
    if not rows:
        return None, f'ยังไม่มี{what}ในบ้านนี้ครับ'
    q = (query or '').strip().casefold()
    if not q:
        if len(rows) == 1: return rows[0], None
        matches = rows
    else:
        matches = [r for r in rows if q in label_fn(r).casefold() or label_fn(r).casefold() in q]
        exact = [r for r in matches if label_fn(r).casefold() == q]
        if len(exact) == 1: return exact[0], None
    if len(matches) == 1: return matches[0], None
    names = '\n'.join(f'• {label_fn(r)}' for r in (matches or rows))
    head = f'พบ{what}หลายรายการ ระบุชื่อให้ชัดขึ้นอีกนิดครับ' if matches else f'ไม่พบ{what}ชื่อ “{query}”'
    return None, f'{head}\n\n{names}'


def _house_expense(text, user_id, h):
    rest = text[len('บ้าน'):].strip()
    amount = _num(rest)
    if not amount:
        return 'ลองพิมพ์ เช่น\n• บ้าน ค่าน้ำ 320\n• บ้าน ค่าไฟ 1250\n• บ้าน ซ่อมก๊อกน้ำ 500'
    desc = _strip_num(rest)
    etype = next((t for keys, t in _EXPENSE_TYPES if any(k in desc.casefold() for k in keys)), '🧹 อื่นๆ')
    row = add_house_expense(user_id, h['id'], {'expense_type': etype, 'description': desc, 'amount': amount})
    if row is None: return 'บันทึกค่าใช้จ่ายบ้านไม่สำเร็จครับ'
    notify_house_expense(h['id'], user_id, row)
    return f'🧾 บันทึกค่าใช้จ่ายบ้านแล้ว\n{etype}' + (f' · {desc}' if desc else '') + f'\nจำนวน {_baht(amount)} บาท'


def _loan_payment(text, user_id, h):
    rest = re.sub(r'^จ่าย(?:ค่า)?งวดบ้าน', '', text).strip()
    before, _, after = rest.partition('โปะ')
    amount, extra = _num(before), (_num(after) or 0)
    if not amount:
        return ('ลองพิมพ์ เช่น\n• จ่ายงวดบ้าน 20000\n• จ่ายงวดบ้าน 20000 โปะ 5000\n\n'
                'ยอดที่พิมพ์คือยอดจ่ายทั้งหมด ส่วนโปะเป็นส่วนหนึ่งของยอดนั้น (เหมือนใน Dashboard)')
    if get_mortgage(h['id']) is None:
        return 'ยังไม่ได้ตั้งข้อมูลสินเชื่อบ้านใน Dashboard ครับ'
    try:
        m = add_mortgage_payment(user_id, h['id'], {'amount': amount, 'extra_principal': extra})
    except ValueError as e:
        return f'⚠️ {e}'
    if m is None: return 'บันทึกค่างวดไม่สำเร็จครับ'
    notify_loan_payment(h['id'], user_id, m)
    last = max(m['payments'], key=lambda x: int(x.get('id') or 0))
    ex = float(last.get('extra_principal') or 0)
    paid = sum(float(x.get('principal') or 0) + float(x.get('extra_principal') or 0) for x in m['payments'])
    balance = max(0.0, float(m.get('loan_amount') or 0) - paid)
    lines = ['🏡 บันทึกค่างวดบ้านแล้ว', f'ยอดชำระ {_baht(last["amount"])} บาท',
             f'เงินต้น {_baht(float(last.get("principal") or 0))} · ดอกเบี้ย {_baht(last.get("interest"))}']
    if ex > 0: lines.append(f'โปะ {_baht(ex)} บาท (รวมอยู่ในยอดชำระ)')
    lines.append(f'เงินต้นคงเหลือ ≈ {_baht(balance)} บาท')
    return '\n'.join(lines)


def _installment(text, user_id, h):
    rest = text[len('ผ่อน'):].strip()
    amount = _num(rest)
    name = _strip_num(rest)
    plans = get_installments(h['id'])
    plan, msg = _pick(plans, name, lambda p: str(p.get('name') or ''), 'รายการผ่อน')
    if plan is None: return msg + ('\n\nตัวอย่าง: ผ่อน เครื่องซักผ้า 1500' if plans else '')
    amount = amount or float(plan.get('monthly_payment') or 0)
    if amount <= 0: return f'ระบุยอดด้วยครับ เช่น “ผ่อน {plan["name"]} 1500”'
    rows = add_installment_payment(user_id, h['id'], {'plan_id': plan['id'], 'amount': amount})
    if rows is None: return 'บันทึกยอดผ่อนไม่สำเร็จครับ'
    notify_installment_payment(h['id'], user_id, rows, plan['id'], amount)
    new = next((p for p in rows if int(p['id']) == int(plan['id'])), plan)
    total = int(new.get('total_installments') or 0)
    return (f'💳 บันทึกยอดผ่อนแล้ว\n{new["name"]}\nยอดงวดนี้ {_baht(amount)} บาท\n'
            f'งวดที่ {new.get("paid_count")}' + (f'/{total}' if total else '') +
            f'\nคงเหลือ ≈ {_baht(new.get("remaining"))} บาท')


def _insurance(text, user_id, h):
    rest = text[len('จ่ายประกัน'):].strip()
    amount = _num(rest)
    name = _strip_num(rest)
    ins_all = get_house_insurance(h['id'])
    label = lambda i: ' '.join(x for x in (str(i.get('insurance_type') or ''), str(i.get('provider') or '')) if x).strip()
    ins, msg = _pick(ins_all, name, label, 'ประกัน')
    if ins is None: return msg + ('\n\nตัวอย่าง: จ่ายประกัน MRTA 1500' if ins_all else '')
    if str(ins.get('payment_method')) != 'ผ่อนแยก':
        return f'ประกัน “{label(ins)}” ไม่ได้ตั้งเป็นแบบผ่อนแยก จึงบันทึกงวดผ่านแชทไม่ได้ครับ'
    data = {'insurance_id': ins['id']}
    if amount: data['amount'] = amount
    try:
        row = add_house_insurance_payment(user_id, h['id'], data)
    except ValueError as e:
        return f'⚠️ {e}'
    if row is None: return 'บันทึกงวดประกันไม่สำเร็จครับ (ตรวจข้อมูลประกันใน Dashboard)'
    notify_insurance_payment(h['id'], user_id, row)
    last = max(row['payments'], key=lambda x: int(x.get('id') or 0))
    total = int(row.get('financed_installments') or 0)
    return (f'🛡️ บันทึกงวดประกันแล้ว\n{label(row)}\nยอดชำระ {_baht(last["amount"])} บาท\n'
            f'งวดที่ {len(row["payments"])}' + (f'/{total}' if total else ''))


def handle_house_chat(text, user_id):
    t = (text or '').strip()
    if re.match(r'^บ้าน\s', t): kind, feature, fn = 'expense', 'loan', _house_expense
    elif re.match(r'^จ่าย(?:ค่า)?งวดบ้าน', t): kind, feature, fn = 'loan', 'loan', _loan_payment
    elif re.match(r'^จ่ายประกัน(?:\s|$)', t): kind, feature, fn = 'insurance', 'loan', _insurance
    elif re.match(r'^ผ่อน(?:\s|$)', t): kind, feature, fn = 'installment', 'installment', _installment
    else: return None
    h = get_active_household(user_id)
    if not h: return _NO_HOUSE
    if not user_has_feature(user_id, h['id'], feature): return _NO_FEATURE
    try:
        return fn(t, user_id, h)
    except Exception as e:
        print('house chat error:', repr(e))
        return 'บันทึกไม่สำเร็จครับ ลองใหม่อีกครั้ง หรือบันทึกผ่าน Dashboard'
