import os, sqlite3, secrets, json
from datetime import datetime
from zoneinfo import ZoneInfo

DB_PATH = os.getenv('DATABASE_PATH', 'moneymate.db')
TZ = ZoneInfo(os.getenv('TZ', 'Asia/Bangkok'))
CATEGORIES = ['อาหาร','บ้าน','เดินทาง','ช้อปปิ้ง','บิล/ค่าสาธารณูปโภค','สุขภาพ','บันเทิง','ท่องเที่ยว','เงินออม/ลงทุน','เงินเดือน','ธุรกิจ','อื่นๆ']


def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with conn() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY, display_name TEXT DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL)''')
        c.execute('''CREATE TABLE IF NOT EXISTS households (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, invite_code TEXT UNIQUE NOT NULL,
            owner_user_id TEXT NOT NULL, created_at TEXT NOT NULL)''')
        c.execute('''CREATE TABLE IF NOT EXISTS household_members (
            household_id INTEGER NOT NULL, user_id TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'member',
            joined_at TEXT NOT NULL, PRIMARY KEY (household_id, user_id))''')
        c.execute('''CREATE TABLE IF NOT EXISTS user_active_household (
            user_id TEXT PRIMARY KEY, household_id INTEGER NOT NULL)''')
        c.execute('''CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, household_id INTEGER,
            type TEXT NOT NULL CHECK(type IN ('income','expense')), amount REAL NOT NULL, category TEXT NOT NULL,
            merchant TEXT, note TEXT, occurred_at TEXT NOT NULL, source TEXT, original_text TEXT, created_at TEXT NOT NULL,
            payer_user_id TEXT, split_mode TEXT DEFAULT 'self', split_participants TEXT DEFAULT '[]', split_amounts TEXT DEFAULT '{}')''')
        cols = {r['name'] for r in c.execute('PRAGMA table_info(transactions)').fetchall()}
        migrations = {
            'household_id': 'ALTER TABLE transactions ADD COLUMN household_id INTEGER',
            'payer_user_id': 'ALTER TABLE transactions ADD COLUMN payer_user_id TEXT',
            'split_mode': "ALTER TABLE transactions ADD COLUMN split_mode TEXT DEFAULT 'self'",
            'split_participants': "ALTER TABLE transactions ADD COLUMN split_participants TEXT DEFAULT '[]'",
            'split_amounts': "ALTER TABLE transactions ADD COLUMN split_amounts TEXT DEFAULT '{}'",
        }
        for col, sql in migrations.items():
            if col not in cols: c.execute(sql)
        c.execute('CREATE INDEX IF NOT EXISTS idx_tx_user_date ON transactions(user_id, occurred_at)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_tx_house_date ON transactions(household_id, occurred_at)')
        c.commit()


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
            except sqlite3.IntegrityError: continue
    raise RuntimeError('could not create household')


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
    where = f'substr(occurred_at,1,7)=? AND {scope}'; qparams = [month] + params
    with conn() as c:
        total = c.execute(f'SELECT type,COALESCE(SUM(amount),0) total FROM transactions WHERE {where} GROUP BY type', qparams).fetchall()
        cats = c.execute(f"SELECT category,type,COALESCE(SUM(amount),0) total,COUNT(*) count FROM transactions WHERE {where} AND type='expense' GROUP BY category ORDER BY total DESC", qparams).fetchall()
        count = c.execute(f'SELECT COUNT(*) FROM transactions WHERE {where}', qparams).fetchone()[0]
    income = next((r['total'] for r in total if r['type']=='income'), 0); expense = next((r['total'] for r in total if r['type']=='expense'), 0)
    return {'month':month,'income':income,'expense':expense,'balance':income-expense,'count':count,'categories':[dict(r) for r in cats]}


def get_recent(limit=20, user_id=None, household_id=None):
    scope, params = _scope(user_id, household_id)
    with conn() as c:
        rows=c.execute(f'SELECT * FROM transactions WHERE {scope} ORDER BY occurred_at DESC,id DESC LIMIT ?', params+[limit]).fetchall()
    return [dict(r) for r in rows]


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
        rows = c.execute("SELECT * FROM transactions WHERE household_id=? AND type='expense' AND substr(occurred_at,1,7)=?", (household_id, month)).fetchall()
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
