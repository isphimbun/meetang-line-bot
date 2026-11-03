"""แจ้งเตือนอัตโนมัติรายวัน (รันใน background thread ของแอป)

- 🔔 ค่างวดบ้านใกล้ครบกำหนด (3 วัน / 1 วัน / วันนี้)
- 💳 งวดผ่อนใกล้ครบกำหนด (ตามวันครบกำหนดของแต่ละแผน)
- 🛡️ ประกัน: งวดผ่อนแยกใกล้ครบกำหนด และเบี้ยประกันใกล้ครบกำหนด (30 / 7 / 1 วัน / วันนี้)
- 📈 อัตราดอกเบี้ยจะเปลี่ยนช่วงใหม่ (ล่วงหน้า 7 วัน / 1 วัน)

ส่งเฉพาะสมาชิกที่มีสิทธิ์ฟีเจอร์นั้น และไม่ส่งซ้ำ (จำใน reminder_log) ตั้งเวลาด้วย REMINDER_HOUR (ค่าเริ่มต้น 8 โมง) ปิดด้วย REMINDERS=0
"""
import os, time, threading
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

import database as db
from notify import broadcast, _bubble, _baht, _thai_date

TZ = ZoneInfo(os.getenv('TZ', 'Asia/Bangkok'))
HOUR = int(os.getenv('REMINDER_HOUR', '8'))


def _when(days):
    return 'วันนี้' if days == 0 else ('พรุ่งนี้' if days == 1 else f'อีก {days} วัน')


def _once(key, hid, feature, builder):
    if db.reminder_seen(key): return False
    db.reminder_mark(key)
    broadcast(hid, feature, builder)
    return True


def _mortgage(hid, m, today):
    pays = sorted(str(p['payment_date'])[:10] for p in m.get('payments', []))
    fc = [r for r in db.mortgage_forecast(m, int(m.get('term_years') or 30) * 12 + len(pays)) if not r.get('actual')]
    if not fc: return
    row = fc[0]; due = date.fromisoformat(row['date']); day = int(m.get('payment_day') or 31)
    if pays and (due - date.fromisoformat(pays[-1])).days <= 10:   # จ่ายก่อนกำหนดไปแล้ว → รอบถัดไป
        due = db._next_due(due.isoformat(), day)
        nxt = [r for r in fc if r['date'] == due.isoformat()]
        row = nxt[0] if nxt else row
    days = (due - today).days
    if days in (3, 1, 0):
        _once(f'mort:{hid}:{due}:{days}', hid, 'loan', lambda h: _bubble(
            f'ค่างวดบ้านครบกำหนด {_when(days)}', '🔔 ค่างวดบ้านใกล้ครบกำหนด', f'ครบกำหนด{_when(days)} ({_thai_date(due.isoformat())})',
            [('ค่างวดตามสัญญา', _baht(m.get('monthly_payment'))), ('ดอกเบี้ยประมาณ', _baht(row.get('interest'))), ('อัตราดอกเบี้ย', f"{row.get('rate', 0):g}%")],
            f"แจ้งสมาชิกบ้าน {h['name']}"))
    # อัตราดอกเบี้ยเปลี่ยน
    for r in m.get('rates') or []:
        sd = str(r.get('start_date') or '')[:10]
        if not sd or sd <= str(m.get('start_date') or '')[:10]: continue
        try: d0 = date.fromisoformat(sd)
        except ValueError: continue
        dd = (d0 - today).days
        if dd in (7, 1):
            rate = db._rate_value(m, r)
            _once(f'rate:{hid}:{sd}:{dd}', hid, 'loan', lambda h: _bubble(
                'อัตราดอกเบี้ยบ้านจะเปลี่ยน', '📈 อัตราดอกเบี้ยจะเปลี่ยน', f'เริ่ม{_when(dd)} ({_thai_date(sd)})',
                [('ช่วง', r.get('label') or 'ช่วงใหม่'), ('อัตราใหม่', f'{rate:g}% ต่อปี')], f"แจ้งสมาชิกบ้าน {h['name']}"))


def _installments(hid, today):
    for p in db.get_installments(hid):
        total = int(p.get('total_installments') or 0)
        if total and p['paid_count'] >= total: continue
        if str(p.get('status') or '') in ('ผ่อนครบ', 'ปิดแล้ว', 'closed'): continue
        day = int(p.get('due_day') or 1)
        due = db._due_on(today.year, today.month, day)
        if due < today: due = db._next_due(today.isoformat(), day)
        last = max([str(x['payment_date'])[:10] for x in p['payments']] or [''])
        if last and abs((due - date.fromisoformat(last)).days) <= 20: continue   # รอบนี้จ่ายแล้ว
        days = (due - today).days
        if days in (3, 1, 0):
            _once(f'inst:{p["id"]}:{due}:{days}', hid, 'installment', lambda h: _bubble(
                f"งวดผ่อน {p['name']} ครบกำหนด {_when(days)}", '💳 งวดผ่อนใกล้ครบกำหนด', f'ครบกำหนด{_when(days)} ({_thai_date(due.isoformat())})',
                [('รายการ', p['name']), ('ค่างวด', _baht(p.get('monthly_payment'))),
                 ('งวดที่', f"{p['paid_count'] + 1}" + (f'/{total}' if total else ''))], f"แจ้งสมาชิกบ้าน {h['name']}"))


def _insurance(hid, m, today):
    for ins in db.get_house_insurance(hid):
        name = ins.get('insurance_type') or 'ประกัน'
        if str(ins.get('payment_method')) == 'ผ่อนแยก':
            fc = [r for r in db.insurance_forecast(ins, m, int(ins.get('financed_installments') or 120)) if not r.get('actual')]
            if not fc: continue
            due = date.fromisoformat(fc[0]['date']); days = (due - today).days
            if days in (3, 1, 0):
                _once(f'insp:{ins["id"]}:{due}:{days}', hid, 'loan', lambda h: _bubble(
                    f'งวดประกัน {name} ครบกำหนด {_when(days)}', '🛡️ งวดประกันใกล้ครบกำหนด', f'ครบกำหนด{_when(days)} ({_thai_date(due.isoformat())})',
                    [('ประกัน', name), ('ยอดงวดนี้', _baht(fc[0].get('payment')))], f"แจ้งสมาชิกบ้าน {h['name']}"))
        elif ins.get('due_date') and str(ins.get('status') or '') not in ('ยกเลิก', 'หมดอายุ'):
            try: due = date.fromisoformat(str(ins['due_date'])[:10])
            except ValueError: continue
            days = (due - today).days
            if days in (30, 7, 1, 0):
                _once(f'ins:{ins["id"]}:{due}:{days}', hid, 'loan', lambda h: _bubble(
                    f'เบี้ยประกัน {name} ครบกำหนด {_when(days)}', '🛡️ เบี้ยประกันใกล้ครบกำหนด', f'ครบกำหนด{_when(days)} ({_thai_date(due.isoformat())})',
                    [('ประกัน', name), ('เบี้ย', _baht(ins.get('amount')))], f"แจ้งสมาชิกบ้าน {h['name']}"))


def run_once(today=None):
    today = today or datetime.now(TZ).date()
    for hid in db.list_loan_household_ids():
        try:
            m = db.get_mortgage(hid)
            if m: _mortgage(hid, m, today)
            _installments(hid, today)
            _insurance(hid, m, today)
        except Exception as e:
            print('reminder error', hid, repr(e))


def _loop():
    while True:
        try:
            if datetime.now(TZ).hour >= HOUR: run_once()
        except Exception as e:
            print('reminder loop error:', repr(e))
        time.sleep(1800)


def start_reminders():
    if os.getenv('REMINDERS', '1').strip().lower() in ('0', 'false', 'no', 'off'): return
    threading.Thread(target=_loop, daemon=True, name='reminders').start()
