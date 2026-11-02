import os, secrets, json, re
import psycopg2
from psycopg2 import IntegrityError
from psycopg2.extras import DictCursor
from datetime import datetime, date, time
from decimal import Decimal
from zoneinfo import ZoneInfo

DB_PATH = os.getenv('DATABASE_PATH', 'moneymate.db')
TZ = ZoneInfo(os.getenv('TZ', 'Asia/Bangkok'))
CATEGORIES = ['อาหาร','บ้าน','เดินทาง','ช้อปปิ้ง','บิล/ค่าสาธารณูปโภค','สุขภาพ','บันเทิง','ท่องเที่ยว','เงินออม/ลงทุน','เงินเดือน','ธุรกิจ','อื่นๆ']

DEFAULT_COMMANDS = [
    ('เพิ่มรายการ', 'เพิ่มรายการ,add', 'help', 'เปิดวิธีบันทึกรายรับ/รายจ่าย'),
    ('สรุป', 'สรุป,summary,เดือนนี้', 'summary', 'สรุปการเงินเดือนนี้'),
    ('รายการล่าสุด', 'รายการล่าสุด,รายการ,recent', 'recent', 'ดูรายการล่าสุด'),
    ('ลบรายการล่าสุด', 'ลบรายการล่าสุด', 'delete_latest', 'ลบรายการล่าสุด'),
    ('ฝากเงิน', 'ฝากเงิน,ฝาก', 'income', 'บันทึกเงินฝาก/เงินเข้า'),
    ('ถอนเงิน', 'ถอนเงิน,ถอน', 'expense', 'บันทึกเงินถอน/เงินออก'),
    ('เงินเดือน', 'เงินเดือน', 'income', 'บันทึกรายรับจากเงินเดือน'),
]


class PGCursor:
    """Small compatibility layer so MeeTang's existing DB code can use PostgreSQL."""
    ID_TABLES = {
        'households', 'transactions', 'bot_commands', 'mortgages', 'mortgage_rates',
        'mortgage_payments', 'house_insurance', 'house_insurance_payments',
        'house_expenses', 'installment_plans', 'installment_payments'
    }

    def __init__(self, cursor):
        self._cur = cursor
        self._lastrowid = None

    @property
    def lastrowid(self):
        return self._lastrowid

    @property
    def rowcount(self):
        return self._cur.rowcount

    @staticmethod
    def _norm(row):
        """Make PostgreSQL values look like the SQLite values the rest of the code expects.
        DATE/TIMESTAMP -> ISO string, NUMERIC -> float. Without this, code such as
        start_date[:7] or float math on Decimal crashes when Supabase columns are typed."""
        if row is None:
            return row
        for i, v in enumerate(row):
            if isinstance(v, datetime):
                row[i] = v.isoformat(timespec='seconds')
            elif isinstance(v, (date, time)):
                row[i] = v.isoformat()
            elif isinstance(v, Decimal):
                row[i] = float(v)
        return row

    def fetchone(self):
        return self._norm(self._cur.fetchone())

    def fetchall(self):
        return [self._norm(r) for r in self._cur.fetchall()]

    def execute(self, sql, params=None):
        sql = sql.replace('?', '%s')
        stripped = sql.lstrip()

        # SQLite compatibility for the few INSERT OR variants used by MeeTang.
        sql = re.sub(
            r'^INSERT\s+OR\s+IGNORE\s+INTO\s+household_members',
            'INSERT INTO household_members', sql, flags=re.I
        )
        if re.search(r'^INSERT\s+OR\s+REPLACE\s+INTO\s+user_active_household', sql, flags=re.I):
            sql = re.sub(
                r'^INSERT\s+OR\s+REPLACE\s+INTO\s+user_active_household',
                'INSERT INTO user_active_household', sql, flags=re.I
            )
            sql += ' ON CONFLICT (user_id) DO UPDATE SET household_id=EXCLUDED.household_id'
        elif 'INSERT INTO household_members' in sql and 'ON CONFLICT' not in sql.upper():
            sql += ' ON CONFLICT DO NOTHING'

        # PostgreSQL needs RETURNING id instead of SQLite's cursor.lastrowid.
        if re.match(r'^\s*INSERT\s+INTO\s+([a-z_]+)', sql, flags=re.I):
            table_match = re.match(r'^\s*INSERT\s+INTO\s+([a-z_]+)', sql, flags=re.I)
            table = table_match.group(1).lower() if table_match else ''
            if table in self.ID_TABLES and 'RETURNING' not in sql.upper():
                sql += ' RETURNING id'

        try:
            self._cur.execute(sql, params)
        except IntegrityError:
            # psycopg2 marks the whole transaction failed after a constraint error.
            # Roll back here so existing SQLite-style retry logic can continue.
            self._cur.connection.rollback()
            raise
        self._lastrowid = None
        if re.match(r'^\s*INSERT\s+INTO\s+([a-z_]+)', sql, flags=re.I) and 'RETURNING ID' in sql.upper():
            row = self._cur.fetchone()
            if row:
                self._lastrowid = row['id'] if isinstance(row, dict) else row[0]
        return self

    def __getattr__(self, name):
        return getattr(self._cur, name)


class PGConnection:
    def __init__(self, raw):
        self._raw = raw

    def execute(self, sql, params=None):
        cur = PGCursor(self._raw.cursor())
        cur.execute(sql, params)
        return cur

    def cursor(self):
        return self._raw.cursor()

    def commit(self):
        return self._raw.commit()

    def rollback(self):
        return self._raw.rollback()

    def close(self):
        return self._raw.close()

    def __enter__(self):
        self._raw.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type:
                self._raw.rollback()
            else:
                self._raw.commit()
        finally:
            self._raw.close()


def conn():
    database_url = os.getenv('DATABASE_URL', '').strip()
    if not database_url:
        raise RuntimeError('DATABASE_URL is not configured. Add your Supabase PostgreSQL connection string to Render Environment Variables.')
    raw = psycopg2.connect(database_url, cursor_factory=DictCursor, connect_timeout=15, sslmode=os.getenv('PGSSLMODE', 'require'))
    return PGConnection(raw)


def init_db():
    """Supabase schema is created by migration SQL; only seed defaults and sync identity sequences here."""
    with conn() as c:
        count = c.execute('SELECT COUNT(*) FROM bot_commands').fetchone()[0]
        if count == 0:
            now = datetime.now(TZ).isoformat(timespec='seconds')
            for name, aliases, action, description in DEFAULT_COMMANDS:
                c.execute(
                    'INSERT INTO bot_commands(name,aliases,action,description,enabled,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',
                    (name, aliases, action, description, True, now, now)
                )

        # Keep PostgreSQL identity sequences ahead of manually imported IDs.
        for table in ['households','transactions','bot_commands','mortgages','mortgage_rates',
                      'mortgage_payments','house_insurance','house_insurance_payments',
                      'house_expenses','installment_plans','installment_payments']:
            c.execute(
                f"SELECT setval(pg_get_serial_sequence('{table}','id'), COALESCE(MAX(id),1), MAX(id) IS NOT NULL) FROM {table}"
            )


def upsert_user(user_id, display_name=''):
    now = datetime.now(TZ).isoformat(timespec='seconds')
    with conn() as c:
        c.execute('''INSERT INTO users(user_id,display_name,created_at,updated_at) VALUES(?,?,?,?)
                     ON CONFLICT(user_id) DO UPDATE SET display_name=CASE WHEN excluded.display_name!='' THEN excluded.display_name ELSE users.display_name END, updated_at=excluded.updated_at''',
                  (user_id, display_name or '', now, now))
        c.commit()


def set_display_name(user_id, name):
    upsert_user(user_id, name.strip())
    return name.strip()


def create_household(owner_user_id, name='บ้านของเรา'):
    upsert_user(owner_user_id)
    now = datetime.now(TZ).isoformat(timespec='seconds')
    with conn() as c:
        for _ in range(10):
            code = secrets.token_hex(3).upper()
            try:
                cur = c.execute('INSERT INTO households(name,invite_code,owner_user_id,created_at) VALUES(?,?,?,?)', (name, code, owner_user_id, now))
                hid = cur.lastrowid
                c.execute('INSERT INTO household_members(household_id,user_id,role,joined_at) VALUES(?,?,?,?)', (hid, owner_user_id, 'owner', now))
                c.execute('INSERT OR REPLACE INTO user_active_household(user_id,household_id) VALUES(?,?)', (owner_user_id, hid))
                c.commit(); return get_household(hid)
            except IntegrityError: continue
    raise RuntimeError('could not create household')



def rename_household(user_id, household_id, name):
    name = (name or '').strip()[:80]
    if not name: return False
    with conn() as c:
        ok = c.execute('SELECT 1 FROM households WHERE id=? AND owner_user_id=?', (household_id, user_id)).fetchone()
        if not ok: return False
        c.execute('UPDATE households SET name=? WHERE id=?', (name, household_id))
        c.commit(); return True


def delete_household(user_id, household_id):
    with conn() as c:
        h = c.execute('SELECT * FROM households WHERE id=? AND owner_user_id=?', (household_id, user_id)).fetchone()
        if not h: return None
        member_ids = [r['user_id'] for r in c.execute('SELECT user_id FROM household_members WHERE household_id=?', (household_id,)).fetchall()]
        c.execute('DELETE FROM transactions WHERE household_id=?', (household_id,))
        c.execute('DELETE FROM household_members WHERE household_id=?', (household_id,))
        c.execute('DELETE FROM user_active_household WHERE household_id=?', (household_id,))
        c.execute('DELETE FROM households WHERE id=?', (household_id,))
        for uid in member_ids:
            nxt = c.execute("SELECT h.id FROM household_members hm JOIN households h ON h.id=hm.household_id WHERE hm.user_id=? ORDER BY h.created_at DESC LIMIT 1", (uid,)).fetchone()
            if nxt:
                c.execute('INSERT OR REPLACE INTO user_active_household(user_id,household_id) VALUES(?,?)', (uid, nxt['id']))
        c.commit()
        return dict(h)


def leave_household(user_id, household_id):
    with conn() as c:
        h = c.execute('SELECT * FROM households WHERE id=?', (household_id,)).fetchone()
        if not h or h['owner_user_id'] == user_id: return False
        ok = c.execute('DELETE FROM household_members WHERE household_id=? AND user_id=?', (household_id, user_id)).rowcount > 0
        c.execute('DELETE FROM user_active_household WHERE user_id=? AND household_id=?', (user_id, household_id))
        if ok:
            nxt = c.execute("SELECT h.id FROM household_members hm JOIN households h ON h.id=hm.household_id WHERE hm.user_id=? ORDER BY h.created_at DESC LIMIT 1", (user_id,)).fetchone()
            if nxt:
                c.execute('INSERT OR REPLACE INTO user_active_household(user_id,household_id) VALUES(?,?)', (user_id, nxt['id']))
        c.commit(); return ok

def join_household(user_id, invite_code):
    code = invite_code.strip().upper(); now = datetime.now(TZ).isoformat(timespec='seconds')
    with conn() as c:
        h = c.execute('SELECT * FROM households WHERE invite_code=?', (code,)).fetchone()
        if not h: return None
        c.execute('INSERT OR IGNORE INTO household_members(household_id,user_id,role,joined_at) VALUES(?,?,?,?)', (h['id'], user_id, 'member', now))
        c.execute('INSERT OR REPLACE INTO user_active_household(user_id,household_id) VALUES(?,?)', (user_id, h['id']))
        c.commit(); return get_household(h['id'])


def get_household(household_id):
    with conn() as c:
        h = c.execute('SELECT * FROM households WHERE id=?', (household_id,)).fetchone()
        if not h: return None
        members = c.execute('''SELECT hm.user_id,hm.role,u.display_name FROM household_members hm LEFT JOIN users u ON u.user_id=hm.user_id WHERE hm.household_id=? ORDER BY hm.joined_at''', (household_id,)).fetchall()
    out = dict(h); out['members'] = [dict(x) for x in members]; return out


def get_active_household(user_id):
    with conn() as c:
        r = c.execute('SELECT h.* FROM user_active_household a JOIN households h ON h.id=a.household_id WHERE a.user_id=?', (user_id,)).fetchone()
    return dict(r) if r else None


def get_user_households(user_id):
    with conn() as c:
        rows = c.execute('SELECT h.*, hm.role FROM household_members hm JOIN households h ON h.id=hm.household_id WHERE hm.user_id=? ORDER BY h.created_at', (user_id,)).fetchall()
    return [dict(r) for r in rows]


def set_active_household(user_id, household_id):
    with conn() as c:
        ok = c.execute('SELECT 1 FROM household_members WHERE household_id=? AND user_id=?', (household_id, user_id)).fetchone()
        if not ok: return False
        c.execute('INSERT OR REPLACE INTO user_active_household(user_id,household_id) VALUES(?,?)', (user_id, household_id)); c.commit(); return True


def _normalise_split(amount, payer_user_id, split_mode='self', participants=None, split_amounts=None):
    participants = participants or [payer_user_id]
    if payer_user_id not in participants: participants = [payer_user_id] + participants
    participants = list(dict.fromkeys(participants))
    if split_mode == 'equal':
        share = round(float(amount) / len(participants), 2)
        amounts = {u: share for u in participants}
        # absorb rounding remainder in last participant
        amounts[participants[-1]] = round(float(amount) - sum(amounts.values()) + amounts[participants[-1]], 2)
        return participants, amounts
    if split_mode == 'percent' and split_amounts:
        total = float(amount)
        amounts = {str(k): round(total * float(v) / 100.0, 2) for k, v in split_amounts.items()}
        diff = round(total - sum(amounts.values()), 2)
        if amounts and abs(diff) > 0.001:
            last = list(amounts)[-1]; amounts[last] = round(amounts[last] + diff, 2)
        return participants, amounts
    if split_mode == 'custom' and split_amounts:
        amounts = {str(k): round(float(v), 2) for k, v in split_amounts.items()}
        diff = round(float(amount) - sum(amounts.values()), 2)
        if amounts and abs(diff) > 0.01:
            last = list(amounts)[-1]; amounts[last] = round(amounts[last] + diff, 2)
        return participants, amounts
    return [payer_user_id], {payer_user_id: round(float(amount), 2)}


def add_transaction(user_id, type, amount, category='อื่นๆ', merchant='', note='', occurred_at=None, source='text', original_text='', household_id=None,
                    payer_user_id=None, split_mode='self', split_participants=None, split_amounts=None):
    occurred_at = occurred_at or datetime.now(TZ).isoformat(timespec='seconds')
    if household_id is None:
        h = get_active_household(user_id); household_id = h['id'] if h else None
    payer_user_id = payer_user_id or user_id
    participants, amounts = _normalise_split(amount, payer_user_id, split_mode, split_participants, split_amounts)
    with conn() as c:
        cur = c.execute('''INSERT INTO transactions(user_id,household_id,type,amount,category,merchant,note,occurred_at,source,original_text,created_at,payer_user_id,split_mode,split_participants,split_amounts)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (user_id, household_id, type, float(amount), category, merchant or '', note or '', occurred_at, source, original_text,
             datetime.now(TZ).isoformat(timespec='seconds'), payer_user_id, split_mode, json.dumps(participants, ensure_ascii=False), json.dumps(amounts, ensure_ascii=False)))
        row = c.execute('SELECT * FROM transactions WHERE id=?', (cur.lastrowid,)).fetchone(); c.commit(); return dict(row)


def _scope(user_id=None, household_id=None):
    if household_id is not None: return 'household_id=?', [household_id]
    if user_id: return 'user_id=?', [user_id]
    return '1=1', []


def get_summary(month=None, user_id=None, household_id=None):
    month = month or datetime.now(TZ).strftime('%Y-%m'); scope, params = _scope(user_id, household_id)
    where = f'substr(CAST(occurred_at AS TEXT),1,7)=? AND {scope}'; qparams = [month] + params
    with conn() as c:
        total = c.execute(f'SELECT type,COALESCE(SUM(amount),0) total FROM transactions WHERE {where} GROUP BY type', qparams).fetchall()
        cats = c.execute(f"SELECT category,type,COALESCE(SUM(amount),0) total,COUNT(*) count FROM transactions WHERE {where} AND type='expense' GROUP BY category,type ORDER BY total DESC", qparams).fetchall()
        count = c.execute(f'SELECT COUNT(*) FROM transactions WHERE {where}', qparams).fetchone()[0]
    income = next((r['total'] for r in total if r['type']=='income'), 0); expense = next((r['total'] for r in total if r['type']=='expense'), 0)
    return {'month':month,'income':income,'expense':expense,'balance':income-expense,'count':count,'categories':[dict(r) for r in cats]}


def get_recent(limit=20, user_id=None, household_id=None):
    scope, params = _scope(user_id, household_id)
    with conn() as c:
        rows=c.execute(f'SELECT * FROM transactions WHERE {scope} ORDER BY occurred_at DESC,id DESC LIMIT ?', params+[limit]).fetchall()
    return [dict(r) for r in rows]



def get_all_user_ids():
    with conn() as c:
        rows = c.execute("SELECT user_id FROM users WHERE user_id IS NOT NULL AND user_id <> ''").fetchall()
    return [r['user_id'] for r in rows]


FEATURES = {
    'loan': '🏠 บ้าน & สินเชื่อ',
    'installment': '💳 รายการผ่อน',
}

def is_super_admin(user_id):
    configured = (os.getenv('SUPER_ADMIN_USER_ID') or '').strip()
    return bool(configured and str(user_id or '').strip() == configured)

def get_global_feature_permissions(requester_user_id):
    if not is_super_admin(requester_user_id):
        return None
    with conn() as c:
        users = [dict(r) for r in c.execute('SELECT user_id,display_name,created_at FROM users ORDER BY created_at').fetchall()]
        rows = c.execute('SELECT user_id,feature,enabled FROM global_feature_permissions').fetchall()
    enabled = {}
    for r in rows:
        enabled.setdefault(r['user_id'], {f: False for f in FEATURES})[r['feature']] = bool(r['enabled'])
    members = []
    for u in users:
        members.append({**u, 'features': enabled.get(u['user_id'], {f: False for f in FEATURES})})
    return {'features': FEATURES, 'users': members}

def set_global_feature(requester_user_id, member_user_id, feature, enabled):
    if not is_super_admin(requester_user_id): return False
    if feature not in FEATURES: return False
    with conn() as c:
        exists = c.execute('SELECT 1 FROM users WHERE user_id=?', (member_user_id,)).fetchone()
        if not exists: return False
        now = datetime.now(TZ).isoformat(timespec='seconds')
        c.execute("""INSERT INTO global_feature_permissions(user_id,feature,enabled,updated_at) VALUES(?,?,?,?)
                     ON CONFLICT(user_id,feature) DO UPDATE SET enabled=excluded.enabled, updated_at=excluded.updated_at""",
                  (member_user_id, feature, bool(enabled), now))
        c.commit()
    return True

def global_user_has_feature(user_id, feature):
    if feature not in FEATURES: return False
    if is_super_admin(user_id): return True
    with conn() as c:
        r = c.execute('SELECT enabled FROM global_feature_permissions WHERE user_id=? AND feature=?', (user_id, feature)).fetchone()
    return bool(r and r['enabled'])

def is_household_admin(user_id, household_id):
    with conn() as c:
        r = c.execute('SELECT role FROM household_members WHERE household_id=? AND user_id=?', (household_id, user_id)).fetchone()
    return bool(r and r['role'] in ('owner', 'admin'))

def set_member_role(requester_user_id, household_id, member_user_id, role):
    if not is_household_admin(requester_user_id, household_id): return False
    role = role if role in ('member','admin') else 'member'
    with conn() as c:
        h = c.execute('SELECT owner_user_id FROM households WHERE id=?', (household_id,)).fetchone()
        m = c.execute('SELECT user_id,role FROM household_members WHERE household_id=? AND user_id=?', (household_id, member_user_id)).fetchone()
        if not h or not m: return False
        if member_user_id == h['owner_user_id']: return False
        c.execute('UPDATE household_members SET role=? WHERE household_id=? AND user_id=?', (role, household_id, member_user_id))
        c.commit(); return True

def get_member_permissions(requester_user_id, household_id):
    h = get_household(household_id)
    if not h or not any(m['user_id'] == requester_user_id for m in h.get('members', [])):
        return None
    with conn() as c:
        rows = c.execute('SELECT user_id,feature,enabled FROM household_feature_permissions WHERE household_id=?', (household_id,)).fetchall()
    perms = {}
    for m in h.get('members', []):
        perms[m['user_id']] = {f: False for f in FEATURES}
    for r in rows:
        perms.setdefault(r['user_id'], {f: False for f in FEATURES})[r['feature']] = bool(r['enabled'])
    return {
        'household_id': household_id,
        'is_admin': is_household_admin(requester_user_id, household_id),
        'features': FEATURES,
        'members': [dict(m, permissions=perms.get(m['user_id'], {f: False for f in FEATURES}), is_admin=m['role'] in ('owner','admin')) for m in h.get('members', [])]
    }

def set_member_features(requester_user_id, household_id, member_user_id, features):
    if not is_household_admin(requester_user_id, household_id): return False
    with conn() as c:
        member = c.execute('SELECT 1 FROM household_members WHERE household_id=? AND user_id=?', (household_id, member_user_id)).fetchone()
        if not member: return False
        now = datetime.now(TZ).isoformat(timespec='seconds')
        for feature in FEATURES:
            enabled = bool((features or {}).get(feature, False))
            sql = '''INSERT INTO household_feature_permissions(household_id,user_id,feature,enabled,updated_at) VALUES(?,?,?,?,?)
                     ON CONFLICT(household_id,user_id,feature) DO UPDATE SET enabled=excluded.enabled, updated_at=excluded.updated_at'''
            c.execute(sql, (household_id, member_user_id, feature, enabled, now))
        c.commit(); return True

def user_has_feature(user_id, household_id, feature):
    # Global Super Admin permissions are authoritative for these system-level features.
    return global_user_has_feature(user_id, feature)

def get_mortgage(household_id):
    with conn() as c:
        m = c.execute('SELECT * FROM mortgages WHERE household_id=?', (household_id,)).fetchone()
        if not m: return None
        rates = c.execute('SELECT * FROM mortgage_rates WHERE mortgage_id=? ORDER BY start_date,id', (m['id'],)).fetchall()
        payments = c.execute('SELECT * FROM mortgage_payments WHERE mortgage_id=? ORDER BY payment_date,id', (m['id'],)).fetchall()
    return {**dict(m), 'rates':[dict(r) for r in rates], 'payments':[dict(x) for x in payments]}

def _blank(v):
    """'' from HTML inputs must become NULL, otherwise PostgreSQL DATE/NUMERIC columns reject it."""
    if v is None: return None
    if isinstance(v, str) and not v.strip(): return None
    return v

def _num(v, default=None):
    v = _blank(v)
    if v is None: return default
    try: return float(v)
    except (TypeError, ValueError): return default


# ===== ดอกเบี้ยรายวัน (Actual/365) =====
# ดอกเบี้ย = ยอดต้นคงเหลือ × อัตรา% ÷ 365 × จำนวนวันจริงนับจากวันจ่ายงวดก่อน (งวดแรกนับจากวันเริ่มสัญญา)
# ตัดทศนิยมทิ้งเป็น 2 ตำแหน่ง (ไม่ปัดขึ้น) ตรงกับที่ธนาคารคิด
from decimal import Decimal, ROUND_DOWN
import calendar as _cal
from datetime import date as _date

def _to_date(v):
    s=str(v)[:10]
    return _date(int(s[:4]),int(s[5:7]),int(s[8:10]))

def accrue_interest(balance, d1, d2, rate_for_ym):
    """ดอกเบี้ยตั้งแต่ d1 ถึง d2 (นับวันจริง, ปีละ 365 วัน). rate_for_ym(ym)->อัตรา% ต่อปีของเดือนนั้น"""
    d1,d2=_to_date(d1),_to_date(d2)
    balance=float(balance or 0)
    if d2<=d1 or balance<=0: return 0.0
    total=Decimal(0); cur=d1
    while cur<d2:
        nxt=_date(cur.year+(1 if cur.month==12 else 0), 1 if cur.month==12 else cur.month+1, 1)
        end=min(nxt,d2); days=(end-cur).days
        rate=Decimal(str(rate_for_ym(f'{cur.year:04d}-{cur.month:02d}') or 0))
        total+=Decimal(str(balance))*rate/Decimal(100)/Decimal(365)*days
        cur=end
    return float(total.quantize(Decimal('0.01'),rounding=ROUND_DOWN))

def _due_on(year, month, day):
    return _date(year,month,min(int(day or 31),_cal.monthrange(year,month)[1]))

def _next_due(prev, day):
    """วันครบกำหนดถัดไปหลังวันที่ prev (day=วันที่ของเดือน; เกินเดือนนั้นใช้วันสุดท้ายของเดือน)"""
    prev=_to_date(prev)
    c=_due_on(prev.year,prev.month,day)
    if c>prev: return c
    y,m=(prev.year+1,1) if prev.month==12 else (prev.year,prev.month+1)
    return _due_on(y,m,day)

def _mortgage_rate_fn(m): return lambda ym:_rate_for_month(m,ym)
def _insurance_rate_fn(ins, mortgage):
    if ins.get('rate_mode')=='custom':
        r=float(ins.get('rate_percent') or 0); return lambda ym:r
    return lambda ym:_rate_for_month(mortgage,ym)

def _ordered(rows):
    return sorted(rows,key=lambda x:(str(x.get('payment_date') or '')[:10],int(x.get('id') or 0)))

def calc_monthly_payment(principal, annual_rate, months):
    principal=float(principal or 0); annual_rate=float(annual_rate or 0); months=int(months or 0)
    if principal<=0 or months<=0: return 0.0
    r=annual_rate/100/12
    if r==0: return round(principal/months,2)
    return round(principal*r/(1-(1+r)**(-months)),2)

def save_mortgage(user_id, household_id, data):
    if not user_has_feature(user_id, household_id, 'loan'): return None
    now=datetime.now(TZ).isoformat(timespec='seconds')
    fields=('property_name','purchase_price','loan_amount','start_date','term_years','monthly_payment','bank','contract_no','payment_day','current_mrr')
    vals=[_blank(data.get(k)) for k in fields]
    # If the user leaves the monthly payment blank, estimate it from the first rate and term.
    try:
        if not float(vals[5] or 0):
            rr=(data.get('rates') or [{}])[0]
            rate=float(rr.get('rate_percent') or 0)
            if rr.get('rate_type')=='mrr': rate=float(data.get('current_mrr') or 0)+float(rr.get('mrr_offset') or 0)
            vals[5]=calc_monthly_payment(vals[2],rate,int(vals[4] or 30)*12)
        else:
            vals[5]=float(vals[5])
        vals[1]=float(vals[1] or 0); vals[2]=float(vals[2] or 0); vals[4]=int(vals[4] or 30); vals[8]=int(vals[8] or 31); vals[9]=float(vals[9] or 0)
    except Exception: pass
    with conn() as c:
        old=c.execute('SELECT id FROM mortgages WHERE household_id=?',(household_id,)).fetchone()
        if old:
            mid=old['id']
            c.execute('UPDATE mortgages SET property_name=?,purchase_price=?,loan_amount=?,start_date=?,term_years=?,monthly_payment=?,bank=?,contract_no=?,payment_day=?,current_mrr=?,updated_at=? WHERE id=?', (*vals,now,mid))
            c.execute('DELETE FROM mortgage_rates WHERE mortgage_id=?',(mid,))
        else:
            cur=c.execute('INSERT INTO mortgages(household_id,property_name,purchase_price,loan_amount,start_date,term_years,monthly_payment,bank,contract_no,payment_day,current_mrr,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(household_id,*vals,now,now)); mid=cur.lastrowid
        for r in data.get('rates',[]):
            c.execute('INSERT INTO mortgage_rates(mortgage_id,start_date,end_date,rate_percent,rate_type,mrr_offset,label) VALUES(?,?,?,?,?,?,?)',(mid,_blank(r.get('start_date')),_blank(r.get('end_date')),_num(r.get('rate_percent'),0.0),r.get('rate_type') or 'fixed',_num(r.get('mrr_offset')),r.get('label') or ''))
        c.commit()
    return get_mortgage(household_id)

def _mortgage_state_before(m, payment_date, exclude_id=0):
    """ยอดต้นคงเหลือ + วันที่จ่ายงวดก่อนหน้า (หรือวันเริ่มสัญญา) ก่อนวัน payment_date"""
    pd=str(payment_date)[:10]
    prior=[x for x in m.get('payments',[]) if int(x.get('id') or 0)!=int(exclude_id or 0) and str(x.get('payment_date') or '')[:10]<pd]
    bal=float(m.get('loan_amount') or 0)-sum(float(x.get('principal') or 0)+float(x.get('extra_principal') or 0) for x in prior)
    prev=max([str(x['payment_date'])[:10] for x in prior] or [str(m.get('start_date') or pd)[:10]])
    return max(0.0,round(bal,2)),prev

def add_mortgage_payment(user_id, household_id, data):
    if not user_has_feature(user_id, household_id, 'loan'): return None
    m=get_mortgage(household_id)
    if not m: return None
    amount=float(data.get('amount') or 0)
    extra=float(data.get('extra_principal') or 0)
    if amount<=0: return None
    payment_date=str(data.get('payment_date') or datetime.now(TZ).date().isoformat())[:10]
    balance,prev=_mortgage_state_before(m,payment_date)
    interest=float(data.get('interest') or 0)
    principal=float(data.get('principal') or 0)
    # ผู้ใช้กรอกแค่ยอดจ่าย — ระบบคิดดอกเบี้ยรายวันและเงินต้นให้เอง
    if interest<=0:
        interest=accrue_interest(balance,prev,payment_date,_mortgage_rate_fn(m))
    if principal<=0:
        principal=round(max(0.0,amount-interest-extra),2)
    if amount < interest:
        raise ValueError(f'ยอดจ่าย {amount:,.2f} ต่ำกว่าดอกเบี้ยงวดนี้ {interest:,.2f}')
    if principal+extra>balance:
        extra=max(0.0,round(balance-principal,2))
        principal=round(max(0.0,balance-extra),2)
    with conn() as c:
        cur=c.execute('INSERT INTO mortgage_payments(mortgage_id,payment_date,amount,principal,interest,extra_principal,note) VALUES(?,?,?,?,?,?,?)',(m['id'],payment_date,amount,principal,interest,extra,data.get('note','')))
        c.commit()
    return get_mortgage(household_id)

def recalc_mortgage_payments(user_id, household_id):
    """คำนวณเงินต้น/ดอกเบี้ยของงวดที่บันทึกไว้แล้วใหม่ทั้งหมดตามสูตรรายวัน (ยอดจ่าย/ยอดโปะคงเดิม)"""
    if not is_household_admin(user_id, household_id): return None
    m=get_mortgage(household_id)
    if not m: return None
    bal=float(m.get('loan_amount') or 0); prev=str(m.get('start_date') or '')[:10]; fn=_mortgage_rate_fn(m); upd=[]
    for p in _ordered(m['payments']):
        d=str(p['payment_date'])[:10]; amt=float(p['amount'] or 0); ex=float(p.get('extra_principal') or 0)
        it=accrue_interest(bal,prev or d,d,fn)
        pr=round(max(0.0,amt-it-ex),2)
        if pr+ex>bal: ex=max(0.0,round(bal-pr,2)); pr=round(max(0.0,bal-ex),2)
        upd.append((pr,it,ex,p['id'])); bal=round(max(0.0,bal-pr-ex),2); prev=d
    with conn() as c:
        for pr,it,ex,pid in upd:
            c.execute('UPDATE mortgage_payments SET principal=?,interest=?,extra_principal=? WHERE id=?',(pr,it,ex,pid))
        c.commit()
    return get_mortgage(household_id)

def _rate_for_month(mortgage, ym):
    if not mortgage: return 0.0
    rates=mortgage.get('rates') or []
    rr=next((r for r in reversed(rates) if (r.get('start_date') or '')[:7] <= ym and (not r.get('end_date') or ym <= (r.get('end_date') or '')[:7])), None)
    if rr and rr.get('rate_type')=='mrr':
        return float(mortgage.get('current_mrr') or 0)+float(rr.get('mrr_offset') or 0)
    return float(rr.get('rate_percent') or 0) if rr else 0.0

def update_mortgage_payment(user_id, household_id, data):
    if not is_household_admin(user_id, household_id): return None
    pid=int(data.get('id') or 0); m=get_mortgage(household_id)
    if not m: return None
    payment_date=str(data.get('payment_date') or datetime.now(TZ).date().isoformat())[:10]; amount=float(data.get('amount') or 0); extra=float(data.get('extra_principal') or 0)
    if amount<=0: return None
    balance,prev=_mortgage_state_before(m,payment_date,pid)
    interest=float(data.get('interest') or 0) or accrue_interest(balance,prev,payment_date,_mortgage_rate_fn(m))
    principal=float(data.get('principal') or 0) or round(max(0,amount-interest-extra),2)
    if amount<interest: raise ValueError(f'ยอดจ่าย {amount:,.2f} ต่ำกว่าดอกเบี้ย {interest:,.2f}')
    principal=min(principal,max(0,balance-extra))
    with conn() as c:
        c.execute('UPDATE mortgage_payments SET payment_date=?,amount=?,principal=?,interest=?,extra_principal=?,note=? WHERE id=? AND mortgage_id=?',(payment_date,amount,principal,interest,extra,data.get('note',''),pid,m['id'])); c.commit()
    return get_mortgage(household_id)

def delete_mortgage_payment(user_id, household_id, payment_id):
    if not is_household_admin(user_id, household_id): return False
    with conn() as c:
        cur=c.execute('DELETE FROM mortgage_payments WHERE id=? AND mortgage_id IN (SELECT id FROM mortgages WHERE household_id=?)',(int(payment_id),household_id)); c.commit(); return cur.rowcount>0

def get_house_insurance(household_id):
    with conn() as c:
        rows=[dict(r) for r in c.execute('SELECT * FROM house_insurance WHERE household_id=? ORDER BY due_date,id',(household_id,)).fetchall()]
        for x in rows:
            x['payments']=[dict(r) for r in c.execute('SELECT * FROM house_insurance_payments WHERE insurance_id=? ORDER BY payment_date,id',(x['id'],)).fetchall()]
    return rows

def save_house_insurance(user_id, household_id, data):
    if not is_household_admin(user_id, household_id): return None
    now=datetime.now(TZ).isoformat(timespec='seconds')
    fields=('insurance_type','provider','amount','payment_cycle','due_date','status','note','payment_method','financed_amount','financed_installments','financed_monthly_payment','financed_start_date','financed_payment_day','rate_mode','rate_percent')
    vals=[_blank(data.get(k)) for k in fields]
    vals[2]=float(vals[2] or 0); vals[8]=float(vals[8] or 0); vals[9]=int(vals[9] or 0); vals[10]=float(vals[10] or 0); vals[12]=int(vals[12] or 31); vals[14]=float(vals[14] or 0)
    with conn() as c:
        iid=int(data.get('id') or 0)
        if iid:
            c.execute('UPDATE house_insurance SET insurance_type=?,provider=?,amount=?,payment_cycle=?,due_date=?,status=?,note=?,payment_method=?,financed_amount=?,financed_installments=?,financed_monthly_payment=?,financed_start_date=?,financed_payment_day=?,rate_mode=?,rate_percent=? WHERE id=? AND household_id=?',(*vals,iid,household_id))
        else:
            cur=c.execute('INSERT INTO house_insurance(household_id,insurance_type,provider,amount,payment_cycle,due_date,status,note,payment_method,financed_amount,financed_installments,financed_monthly_payment,financed_start_date,financed_payment_day,rate_mode,rate_percent) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(household_id,*vals)); iid=cur.lastrowid
        c.commit()
    return next((x for x in get_house_insurance(household_id) if x['id']==iid),None)

def add_house_insurance(user_id, household_id, data):
    return save_house_insurance(user_id, household_id, data)

def _insurance_state_before(ins, payment_date, exclude_id=0):
    pd=str(payment_date)[:10]
    with conn() as c:
        rows=[dict(r) for r in c.execute('SELECT * FROM house_insurance_payments WHERE insurance_id=? AND id<>? ORDER BY payment_date,id',(int(ins['id']),int(exclude_id or 0))).fetchall()]
    prior=[r for r in rows if str(r['payment_date'])[:10]<pd]
    bal=float(ins['financed_amount'] or ins['amount'] or 0)-sum(float(r['principal'] or 0) for r in prior)
    start=str(ins['financed_start_date'] or ins['due_date'] or pd)[:10]
    prev=max([str(r['payment_date'])[:10] for r in prior] or [start])
    return max(0.0,round(bal,2)),prev

def _insurance_payment_calc(ins, mortgage, payment_date, amount, principal, interest, exclude_id=0):
    balance,prev=_insurance_state_before(ins,payment_date,exclude_id)
    fn=_insurance_rate_fn(dict(ins),mortgage)
    rate=fn(str(payment_date)[:7])
    amount=float(amount or 0)
    interest=float(interest or 0)
    principal=float(principal or 0)
    if amount<=0: return None
    if interest<=0: interest=accrue_interest(balance,prev,payment_date,fn)
    if amount < interest: raise ValueError(f'ยอดจ่าย {amount:,.2f} ต่ำกว่าดอกเบี้ยงวดนี้ {interest:,.2f}')
    if principal<=0: principal=round(max(0.0,amount-interest),2)
    principal=min(principal,balance)
    return round(amount,2),round(principal,2),round(interest,2),round(rate,4),round(max(0,balance-principal),2)

def recalc_insurance_payments(user_id, household_id, insurance_id=None):
    """คำนวณเงินต้น/ดอกเบี้ยของงวดประกัน (แบบผ่อนแยก) ที่บันทึกไว้ใหม่ตามสูตรรายวัน"""
    if not is_household_admin(user_id, household_id): return None
    mortgage=get_mortgage(household_id)
    for ins in get_house_insurance(household_id):
        if str(ins.get('payment_method'))!='ผ่อนแยก': continue
        if insurance_id and int(ins['id'])!=int(insurance_id): continue
        bal=float(ins.get('financed_amount') or ins.get('amount') or 0)
        prev=str(ins.get('financed_start_date') or ins.get('due_date') or '')[:10]; fn=_insurance_rate_fn(ins,mortgage); upd=[]
        for p in _ordered(ins['payments']):
            d=str(p['payment_date'])[:10]; amt=float(p['amount'] or 0)
            it=accrue_interest(bal,prev or d,d,fn); pr=min(round(max(0.0,amt-it),2),bal)
            upd.append((pr,it,p['id'])); bal=round(max(0.0,bal-pr),2); prev=d
        with conn() as c:
            for pr,it,pid in upd: c.execute('UPDATE house_insurance_payments SET principal=?,interest=? WHERE id=?',(pr,it,pid))
            c.commit()
    return get_house_insurance(household_id)

def add_house_insurance_payment(user_id, household_id, data):
    if not user_has_feature(user_id, household_id, 'loan'): return None
    iid=int(data.get('insurance_id') or 0)
    payment_date=data.get('payment_date') or datetime.now(TZ).date().isoformat()
    with conn() as c:
        ins=c.execute('SELECT * FROM house_insurance WHERE id=? AND household_id=?',(iid,household_id)).fetchone()
    if not ins or str(ins['payment_method'])!='ผ่อนแยก': return None
    mortgage=get_mortgage(household_id)
    amount=float(data.get('amount') or ins['financed_monthly_payment'] or 0)
    calc=_insurance_payment_calc(ins,mortgage,payment_date,amount,data.get('principal'),data.get('interest'))
    if not calc: return None
    amount,principal,interest,rate,balance=calc
    with conn() as c:
        cur=c.execute('INSERT INTO house_insurance_payments(insurance_id,payment_date,amount,principal,interest,note) VALUES(?,?,?,?,?,?)',(iid,payment_date,amount,principal,interest,data.get('note',''))); c.commit()
    return next((x for x in get_house_insurance(household_id) if x['id']==iid),None)

def update_house_insurance_payment(user_id, household_id, data):
    if not is_household_admin(user_id, household_id): return None
    pid=int(data.get('id') or 0); iid=int(data.get('insurance_id') or 0)
    with conn() as c: ins=c.execute('SELECT * FROM house_insurance WHERE id=? AND household_id=?',(iid,household_id)).fetchone()
    if not ins: return None
    payment_date=data.get('payment_date') or datetime.now(TZ).date().isoformat()
    calc=_insurance_payment_calc(ins,get_mortgage(household_id),payment_date,data.get('amount'),data.get('principal'),data.get('interest'),pid)
    if not calc: return None
    amount,principal,interest,rate,balance=calc
    with conn() as c:
        c.execute('UPDATE house_insurance_payments SET payment_date=?,amount=?,principal=?,interest=?,note=? WHERE id=? AND insurance_id=?',(payment_date,amount,principal,interest,data.get('note',''),pid,iid)); c.commit()
    return next((x for x in get_house_insurance(household_id) if x['id']==iid),None)

def delete_house_insurance_payment(user_id, household_id, payment_id):
    if not is_household_admin(user_id, household_id): return False
    with conn() as c:
        cur=c.execute('DELETE FROM house_insurance_payments WHERE id=? AND insurance_id IN (SELECT id FROM house_insurance WHERE household_id=?)',(int(payment_id),household_id)); c.commit(); return cur.rowcount>0

def delete_house_insurance(user_id, household_id, insurance_id):
    """ลบกรมธรรม์ประกันทั้งรายการ (รวมรายการจ่ายงวดของประกันนั้น) — เฉพาะ owner/admin ของบ้าน"""
    if not is_household_admin(user_id, household_id): return False
    iid=int(insurance_id)
    with conn() as c:
        ok=c.execute('SELECT 1 FROM house_insurance WHERE id=? AND household_id=?',(iid,household_id)).fetchone()
        if not ok: return False
        c.execute('DELETE FROM house_insurance_payments WHERE insurance_id=?',(iid,))
        c.execute('DELETE FROM house_insurance WHERE id=? AND household_id=?',(iid,household_id))
        c.commit()
    return True

def insurance_forecast(insurance, mortgage, months=120):
    """ตารางผ่อนประกัน: งวดที่จ่ายจริงใช้ค่าที่บันทึก งวดถัดไปคิดดอกเบี้ยรายวันจากยอดคงเหลือจริง"""
    if not insurance or str(insurance.get('payment_method'))!='ผ่อนแยก': return []
    balance=float(insurance.get('financed_amount') or insurance.get('amount') or 0)
    payment=float(insurance.get('financed_monthly_payment') or 0)
    n=int(insurance.get('financed_installments') or 0)
    if balance<=0 or n<=0: return []
    start=str(insurance.get('financed_start_date') or insurance.get('due_date') or datetime.now(TZ).date().isoformat())[:10]
    day=int(insurance.get('financed_payment_day') or 31); fn=_insurance_rate_fn(insurance,mortgage)
    rows=[]; prev=start; no=0
    for p in _ordered(insurance.get('payments') or []):
        no+=1; d=str(p['payment_date'])[:10]; pr=float(p.get('principal') or 0); it=float(p.get('interest') or 0)
        balance=round(max(0.0,balance-pr),2)
        rows.append({'no':no,'date':d,'rate':fn(d[:7]),'payment':float(p.get('amount') or 0),'interest':it,'principal':pr,'balance':balance,'actual':True}); prev=d
    due=_next_due(prev,day)
    while balance>0 and no<n and no<months:
        no+=1; ds=due.isoformat(); rate=fn(ds[:7])
        interest=accrue_interest(balance,prev,ds,fn)
        pay=payment if payment>0 else max(interest,round(balance/(n-no+1)+interest,2))
        if no==n: pay=round(balance+interest,2)
        pay=round(min(pay,balance+interest),2); principal=round(max(0,min(pay-interest,balance)),2); end=round(balance-principal,2)
        rows.append({'no':no,'date':ds,'rate':rate,'payment':pay,'interest':interest,'principal':principal,'balance':end})
        balance=end; prev=ds; due=_next_due(prev,day)
    return rows

def get_house_expenses(household_id, month=None):
    with conn() as c:
        if month: rows=c.execute('SELECT * FROM house_expenses WHERE household_id=? AND substr(CAST(expense_date AS TEXT),1,7)=? ORDER BY expense_date DESC,id DESC',(household_id,month)).fetchall()
        else: rows=c.execute('SELECT * FROM house_expenses WHERE household_id=? ORDER BY expense_date DESC,id DESC LIMIT 100',(household_id,)).fetchall()
    return [dict(r) for r in rows]

def add_house_expense(user_id, household_id, data):
    if not user_has_feature(user_id, household_id, 'loan'): return None
    with conn() as c:
        cur=c.execute('INSERT INTO house_expenses(household_id,expense_date,expense_type,description,amount,note) VALUES(?,?,?,?,?,?)',(household_id,data.get('expense_date') or datetime.now(TZ).date().isoformat(),data.get('expense_type','อื่นๆ'),data.get('description',''),float(data.get('amount') or 0),data.get('note',''))); c.commit()
        return dict(c.execute('SELECT * FROM house_expenses WHERE id=?',(cur.lastrowid,)).fetchone())

def mortgage_forecast(mortgage, months=360):
    """ตารางผ่อนบ้าน: งวดที่จ่ายจริงใช้ค่าที่บันทึก (actual=True) งวดต่อไปคิดดอกเบี้ยรายวันจากยอดคงเหลือจริง"""
    if not mortgage: return []
    balance=float(mortgage.get('loan_amount') or 0); payment=float(mortgage.get('monthly_payment') or 0)
    start=str(mortgage.get('start_date') or datetime.now(TZ).date().isoformat())[:10]
    day=int(mortgage.get('payment_day') or 31); fn=_mortgage_rate_fn(mortgage)
    rows=[]; prev=start; no=0
    for p in _ordered(mortgage.get('payments') or []):
        no+=1; d=str(p['payment_date'])[:10]; pr=float(p.get('principal') or 0); ex=float(p.get('extra_principal') or 0)
        balance=round(max(0.0,balance-pr-ex),2)
        rows.append({'no':no,'date':d,'rate':fn(d[:7]),'payment':float(p.get('amount') or 0),'principal':pr,'extra_principal':ex,'interest':float(p.get('interest') or 0),'balance':balance,'actual':True}); prev=d
    due=_next_due(prev,day)
    while balance>0 and no<months:
        no+=1; ds=due.isoformat()
        interest=accrue_interest(balance,prev,ds,fn)
        pay=round(min(payment,balance+interest),2); principal=round(max(0,min(pay-interest,balance)),2); end=round(balance-principal,2)
        rows.append({'no':no,'date':ds,'rate':fn(ds[:7]),'payment':pay,'interest':interest,'principal':principal,'balance':end})
        balance=end; prev=ds; due=_next_due(prev,day)
    return rows


def get_installments(household_id):
    with conn() as c:
        plans=c.execute('SELECT * FROM installment_plans WHERE household_id=? ORDER BY id DESC',(household_id,)).fetchall()
        out=[]
        for p in plans:
            pays=c.execute('SELECT * FROM installment_payments WHERE plan_id=? ORDER BY payment_date,id',(p['id'],)).fetchall()
            d=dict(p); d['payments']=[dict(x) for x in pays]; d['paid_amount']=round(sum(float(x['amount']) for x in pays),2); d['paid_count']=len(pays); d['remaining']=round(max(0,float(p['financed_amount'] or 0)-sum(float(x['principal'] or x['amount']) for x in pays)),2); out.append(d)
    return out

def add_installment(user_id, household_id, data):
    if not is_household_admin(user_id, household_id): return None
    now=datetime.now(TZ).isoformat(timespec='seconds')
    with conn() as c:
        cur=c.execute('INSERT INTO installment_plans(household_id,name,category,total_price,down_payment,financed_amount,total_installments,monthly_payment,start_date,interest_rate,provider,due_day,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(household_id,data.get('name','รายการผ่อน'),data.get('category',''),float(data.get('total_price') or 0),float(data.get('down_payment') or 0),float(data.get('financed_amount') or 0),int(data.get('total_installments') or 0),float(data.get('monthly_payment') or 0),_blank(data.get('start_date')),float(data.get('interest_rate') or 0),data.get('provider',''),int(data.get('due_day') or 1),data.get('status','กำลังผ่อน'),now)); c.commit(); return get_installments(household_id)

def add_installment_payment(user_id, household_id, data):
    if not user_has_feature(user_id, household_id, 'installment'): return None
    plan_id=int(data.get('plan_id') or 0)
    with conn() as c:
        ok=c.execute('SELECT 1 FROM installment_plans WHERE id=? AND household_id=?',(plan_id,household_id)).fetchone()
        if not ok:return None
        c.execute('INSERT INTO installment_payments(plan_id,payment_date,amount,principal,interest,note) VALUES(?,?,?,?,?,?)',(plan_id,data.get('payment_date') or datetime.now(TZ).date().isoformat(),float(data.get('amount') or 0),float(data.get('principal') or data.get('amount') or 0),float(data.get('interest') or 0),data.get('note',''))); c.commit()
    return get_installments(household_id)

def get_categories(): return CATEGORIES


def delete_transaction(tx_id, user_id=None, household_id=None):
    scope, params = _scope(user_id, household_id)
    with conn() as c:
        cur=c.execute(f'DELETE FROM transactions WHERE id=? AND {scope}', [tx_id]+params); c.commit(); return cur.rowcount>0


def get_settlement(household_id, month=None):
    month = month or datetime.now(TZ).strftime('%Y-%m')
    h = get_household(household_id)
    members = {m['user_id']: (m['display_name'] or f'สมาชิก {m["user_id"][-4:]}') for m in h['members']}
    paid = {u: 0.0 for u in members}; owed = {u: 0.0 for u in members}
    with conn() as c:
        rows = c.execute("SELECT * FROM transactions WHERE household_id=? AND type='expense' AND substr(CAST(occurred_at AS TEXT),1,7)=?", (household_id, month)).fetchall()
    for r in rows:
        payer = r['payer_user_id'] or r['user_id']; paid[payer] = paid.get(payer, 0) + float(r['amount'])
        try: amounts = json.loads(r['split_amounts'] or '{}')
        except Exception: amounts = {payer: float(r['amount'])}
        for u, amount in amounts.items(): owed[u] = owed.get(u, 0) + float(amount)
    net = {u: round(paid.get(u,0)-owed.get(u,0),2) for u in members}
    transfers=[]
    creditors=[[u, round(v,2)] for u,v in net.items() if v>0.005]
    debtors=[[u, round(-v,2)] for u,v in net.items() if v<-0.005]
    i=j=0
    while i<len(debtors) and j<len(creditors):
        d,da=debtors[i]; c,ca=creditors[j]; x=round(min(da,ca),2)
        transfers.append({'from_user_id':d,'from_name':members[d],'to_user_id':c,'to_name':members[c],'amount':x})
        debtors[i][1]=round(da-x,2); creditors[j][1]=round(ca-x,2)
        if debtors[i][1] <= 0.005: i+=1
        if creditors[j][1] <= 0.005: j+=1
    return {'month':month, 'members':[{'user_id':u,'name':members[u],'paid':round(paid.get(u,0),2),'owed':round(owed.get(u,0),2),'net':net[u]} for u in members], 'net':net, 'transfers':transfers}


def get_commands(enabled_only=False):
    with conn() as c:
        q = 'SELECT * FROM bot_commands'
        if enabled_only: q += " WHERE CAST(enabled AS TEXT) IN ('1','true','t')"
        rows = c.execute(q + ' ORDER BY id').fetchall()
    return [dict(r) for r in rows]


def add_command(name, aliases, action='custom', description='', enabled=True):
    name=(name or '').strip()[:80]; aliases=(aliases or '').strip()[:300]
    if not name or not aliases: raise ValueError('name and aliases are required')
    now=datetime.now(TZ).isoformat(timespec='seconds')
    with conn() as c:
        cur=c.execute('INSERT INTO bot_commands(name,aliases,action,description,enabled,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',
                      (name,aliases,action,(description or '').strip()[:200],bool(enabled),now,now))
        row=c.execute('SELECT * FROM bot_commands WHERE id=?',(cur.lastrowid,)).fetchone(); c.commit(); return dict(row)


def update_command(command_id, name, aliases, action='custom', description='', enabled=True):
    now=datetime.now(TZ).isoformat(timespec='seconds')
    with conn() as c:
        c.execute('UPDATE bot_commands SET name=?,aliases=?,action=?,description=?,enabled=?,updated_at=? WHERE id=?',
                  ((name or '').strip()[:80],(aliases or '').strip()[:300],action,(description or '').strip()[:200],bool(enabled),now,command_id))
        row=c.execute('SELECT * FROM bot_commands WHERE id=?',(command_id,)).fetchone(); c.commit(); return dict(row) if row else None


def delete_command(command_id):
    with conn() as c:
        cur=c.execute('DELETE FROM bot_commands WHERE id=?',(command_id,)); c.commit(); return cur.rowcount>0


def find_command(text):
    t=(text or '').strip().lower()
    commands=get_commands(True)
    for cmd in commands:
        for alias in cmd['aliases'].split(','):
            a=alias.strip().lower()
            if a and (t==a or t.startswith(a+' ')):
                return cmd, t[len(a):].strip()
    return None, ''
