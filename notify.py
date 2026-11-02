"""แจ้งเตือนสมาชิกในบ้านผ่าน LINE (multicast) เมื่อมีการบันทึกรายการ / ผ่อน / สินเชื่อ

- ส่งหาสมาชิกคนอื่นในบ้านเท่านั้น (ไม่ส่งหาคนที่บันทึกเอง)
- ส่งใน background thread ไม่ทำให้ webhook / API ช้าลง และ error จะไม่ทำให้การบันทึกล้มเหลว
- ปิดทั้งระบบได้ด้วย env NOTIFY_MEMBERS=0
- หมายเหตุ: multicast นับเป็นโควตาข้อความของ LINE OA (นับตามจำนวนผู้รับ)
"""
import os, threading
from datetime import datetime
from zoneinfo import ZoneInfo
import requests

from database import get_household, user_has_feature

TZ = ZoneInfo(os.getenv('TZ', 'Asia/Bangkok'))
_TH_MONTHS = ['ม.ค.', 'ก.พ.', 'มี.ค.', 'เม.ย.', 'พ.ค.', 'มิ.ย.', 'ก.ค.', 'ส.ค.', 'ก.ย.', 'ต.ค.', 'พ.ย.', 'ธ.ค.']


def _token():
    return os.getenv('LINE_ACCESS_TOKEN', '') or os.getenv('LINE_CHANNEL_ACCESS_TOKEN', '')


def _enabled():
    return os.getenv('NOTIFY_MEMBERS', '1').strip().lower() not in ('0', 'false', 'no', 'off')


def _baht(v):
    try:
        v = float(v or 0)
    except (TypeError, ValueError):
        v = 0.0
    return f'{v:,.0f} บาท' if abs(v - round(v)) < 0.005 else f'{v:,.2f} บาท'


def _thai_date(value=None):
    try:
        d = datetime.fromisoformat(str(value)[:10]) if value else datetime.now(TZ)
    except ValueError:
        d = datetime.now(TZ)
    return f'{d.day} {_TH_MONTHS[d.month - 1]} {d.year}'


def _member_name(h, user_id):
    for m in (h or {}).get('members', []):
        if m['user_id'] == user_id:
            return m.get('display_name') or f'สมาชิก {user_id[-4:]}'
    return f'สมาชิก {str(user_id)[-4:]}'


# ---------- Flex builder: หัวข้อ / คำอธิบาย / รายการ bullet / footer ----------
def _t(text, size='sm', color='#3B3338', weight=None, wrap=True, flex=None, margin=None):
    d = {'type': 'text', 'text': str(text), 'size': size, 'color': color, 'wrap': wrap}
    if weight: d['weight'] = weight
    if flex is not None: d['flex'] = flex
    if margin: d['margin'] = margin
    return d


def _bullet(label, value):
    return {'type': 'box', 'layout': 'horizontal', 'margin': 'sm', 'contents': [
        _t('•', 'sm', '#9A8D94', flex=0), _t(f'{label}: {value}', 'sm', '#3B3338', flex=1, margin='sm')]}


def _bubble(alt, title, subtitle, items, footer):
    body = [_t(title, 'md', '#2B2428', 'bold')]
    if subtitle: body.append(_t(subtitle, 'sm', '#3B3338', margin='md'))
    body.append({'type': 'box', 'layout': 'vertical', 'margin': 'md', 'contents': [_bullet(k, v) for k, v in items]})
    body.append(_t(footer, 'xxs', '#9A8D94', margin='lg'))
    return {'type': 'flex', 'altText': alt, 'contents': {
        'type': 'bubble', 'size': 'kilo',
        'body': {'type': 'box', 'layout': 'vertical', 'paddingAll': '16px', 'contents': body}}}


# ---------- ส่งจริง ----------
def _send(user_ids, messages):
    token = _token()
    if not token or not user_ids: return
    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
    for i in range(0, len(user_ids), 500):  # multicast ได้ครั้งละ 500 คน
        try:
            r = requests.post('https://api.line.me/v2/bot/message/multicast', headers=headers,
                              json={'to': user_ids[i:i + 500], 'messages': messages}, timeout=15)
            if r.status_code >= 300: print('notify error:', r.status_code, r.text[:200])
        except Exception as e:
            print('notify error:', repr(e))


def _dispatch(household_id, actor_user_id, builder, feature=None):
    """หา household + สมาชิกที่ต้องแจ้ง แล้วส่งใน thread แยก"""
    if not _enabled() or not household_id: return
    def run():
        try:
            h = get_household(int(household_id))
            if not h: return
            targets = [m['user_id'] for m in h.get('members', []) if m['user_id'] != actor_user_id]
            if feature:  # ข้อมูลบ้าน/สินเชื่อ/ผ่อน ส่งเฉพาะคนที่ได้รับสิทธิ์ฟีเจอร์นั้น
                targets = [u for u in targets if user_has_feature(u, int(household_id), feature)]
            if not targets: return
            _send(targets, [builder(h)])
        except Exception as e:
            print('notify error:', repr(e))
    threading.Thread(target=run, daemon=True).start()


# ---------- 3 เหตุการณ์ ----------
def notify_transaction(tx, actor_user_id):
    """รายการรายรับ/รายจ่ายใหม่"""
    if not tx or not tx.get('household_id'): return
    def build(h):
        is_income = tx.get('type') == 'income'
        what = tx.get('merchant') or tx.get('note') or tx.get('category') or 'อื่นๆ'
        return _bubble(
            f"{h['name']} มีรายการใหม่ {_baht(tx.get('amount'))}",
            f"🏠 {h['name']} มีรายการใหม่",
            'มีการบันทึกรายรับใหม่' if is_income else 'มีการบันทึกค่าใช้จ่ายใหม่',
            [('รายการ', what), ('จำนวน', _baht(tx.get('amount'))),
             ('ผู้บันทึก', _member_name(h, actor_user_id)), ('วันที่', _thai_date(tx.get('occurred_at')))],
            'MeeTang – จัดการเงินบ้านให้ง่ายขึ้น ❤️')
    _dispatch(tx['household_id'], actor_user_id, build)


def notify_installment_payment(household_id, actor_user_id, plans, plan_id, amount):
    """บันทึกจ่ายงวดผ่อน — plans คือค่าที่ add_installment_payment คืนมา"""
    plan = next((p for p in (plans or []) if int(p.get('id') or 0) == int(plan_id or 0)), None)
    if not plan: return
    total = int(plan.get('total_installments') or 0)
    paid = int(plan.get('paid_count') or 0)
    def build(h):
        return _bubble(
            f"มีการบันทึกยอดผ่อนใหม่ {plan.get('name') or ''}",
            '💳 มีการบันทึกยอดผ่อนใหม่', None,
            [('รายการ', plan.get('name') or '-'), ('ยอดงวดนี้', _baht(amount)),
             ('จำนวนงวด', f'{paid}/{total}' if total else str(paid))],
            f"แจ้งสมาชิกบ้าน {h['name']}")
    _dispatch(household_id, actor_user_id, build, feature='installment')


def notify_loan_payment(household_id, actor_user_id, mortgage):
    """บันทึกชำระสินเชื่อบ้าน — mortgage คือค่าที่ add_mortgage_payment คืนมา"""
    pays = (mortgage or {}).get('payments') or []
    if not pays: return
    last = max(pays, key=lambda x: int(x.get('id') or 0))
    extra = float(last.get('extra_principal') or 0)
    def build(h):
        items = [('ยอดชำระ', _baht(last.get('amount'))),
                 ('เงินต้น', _baht(float(last.get('principal') or 0) + extra)),
                 ('ดอกเบี้ย', _baht(last.get('interest')))]
        if extra > 0: items.append(('เงินโปะ (รวมในเงินต้น)', _baht(extra)))
        return _bubble(
            f"แจ้งเตือนสินเชื่อบ้าน ชำระ {_baht(last.get('amount'))}",
            '🏡 แจ้งเตือนสินเชื่อบ้าน', 'มีการบันทึกชำระสินเชื่อแล้ว', items,
            f"แจ้งสมาชิกบ้าน {h['name']}")
    _dispatch(household_id, actor_user_id, build, feature='loan')


def notify_house_expense(household_id, actor_user_id, row):
    """ค่าใช้จ่ายบ้าน (ค่าน้ำ/ไฟ/เน็ต/ส่วนกลาง/ซ่อม) — row คือค่าที่ add_house_expense คืนมา"""
    if not row: return
    def build(h):
        items = [('หมวด', row.get('expense_type') or 'อื่นๆ')]
        if row.get('description'): items.append(('รายละเอียด', row['description']))
        items += [('จำนวน', _baht(row.get('amount'))), ('ผู้บันทึก', _member_name(h, actor_user_id)),
                  ('วันที่', _thai_date(row.get('expense_date')))]
        return _bubble(
            f"{h['name']} มีค่าใช้จ่ายบ้านใหม่ {_baht(row.get('amount'))}",
            f"🧾 {h['name']} มีค่าใช้จ่ายบ้านใหม่", 'มีการบันทึกค่าใช้จ่ายบ้านใหม่', items,
            'MeeTang – จัดการเงินบ้านให้ง่ายขึ้น ❤️')
    _dispatch(household_id, actor_user_id, build, feature='loan')


def notify_insurance_payment(household_id, actor_user_id, insurance):
    """จ่ายงวดประกัน (แบบผ่อนแยก) — insurance คือค่าที่ add_house_insurance_payment คืนมา"""
    pays = (insurance or {}).get('payments') or []
    if not pays: return
    last = max(pays, key=lambda x: int(x.get('id') or 0))
    total = int(insurance.get('financed_installments') or 0)
    name = insurance.get('insurance_type') or 'ประกัน'
    if insurance.get('provider'): name += f" ({insurance['provider']})"
    def build(h):
        items = [('ประกัน', name), ('ยอดชำระ', _baht(last.get('amount')))]
        if float(last.get('interest') or 0) > 0:
            items += [('เงินต้น', _baht(last.get('principal'))), ('ดอกเบี้ย', _baht(last.get('interest')))]
        items.append(('จำนวนงวด', f'{len(pays)}/{total}' if total else str(len(pays))))
        return _bubble(
            f"มีการบันทึกจ่ายประกัน {_baht(last.get('amount'))}",
            '🛡️ มีการบันทึกจ่ายประกันใหม่', None, items, f"แจ้งสมาชิกบ้าน {h['name']}")
    _dispatch(household_id, actor_user_id, build, feature='loan')
