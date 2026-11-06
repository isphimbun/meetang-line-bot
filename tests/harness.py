"""sqlite shim เพื่อทดสอบตรรกะใน database.py (ที่ใช้ PostgreSQL) โดยไม่ต้องมีฐานข้อมูลจริง — ใช้เฉพาะตอนทดสอบ"""
import sys, types, sqlite3, importlib, re, os
def load(path=None):
    path=path or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for n in ('psycopg2','psycopg2.extras'): sys.modules[n]=types.ModuleType(n)
    sys.modules['psycopg2'].IntegrityError=sqlite3.IntegrityError
    sys.modules['psycopg2'].extras=sys.modules['psycopg2.extras']; sys.modules['psycopg2.extras'].DictCursor=object
    sys.path.insert(0,path); sys.modules.pop('database',None)
    db=importlib.import_module('database')
    raw=sqlite3.connect(':memory:',check_same_thread=False); raw.row_factory=sqlite3.Row
    raw.executescript('''
    CREATE TABLE mortgages(id INTEGER PRIMARY KEY AUTOINCREMENT,household_id,property_name,purchase_price,loan_amount,start_date,term_years,monthly_payment,bank,contract_no,payment_day,current_mrr,created_at,updated_at);
    CREATE TABLE mortgage_rates(id INTEGER PRIMARY KEY AUTOINCREMENT,mortgage_id,start_date,end_date,rate_percent,rate_type,mrr_offset,label);
    CREATE TABLE mortgage_payments(id INTEGER PRIMARY KEY AUTOINCREMENT,mortgage_id,payment_date,amount,principal,interest,extra_principal,note);
    CREATE TABLE house_insurance(id INTEGER PRIMARY KEY AUTOINCREMENT,household_id,insurance_type,provider,amount,payment_cycle,due_date,status,note,payment_method,financed_amount,financed_installments,financed_monthly_payment,financed_start_date,financed_payment_day,rate_mode,rate_percent);
    CREATE TABLE house_insurance_payments(id INTEGER PRIMARY KEY AUTOINCREMENT,insurance_id,payment_date,amount,principal,interest,note);
    CREATE TABLE installment_plans(id INTEGER PRIMARY KEY AUTOINCREMENT,household_id,name,category,total_price,down_payment,financed_amount,total_installments,monthly_payment,start_date,interest_rate,provider,due_day,status,created_at);
    CREATE TABLE installment_payments(id INTEGER PRIMARY KEY AUTOINCREMENT,plan_id,payment_date,amount,principal,interest,note);
    CREATE TABLE transactions(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id,household_id,type,amount,category,merchant,note,occurred_at,source,original_text,created_at,payer_user_id,split_mode,split_participants,split_amounts);
    CREATE TABLE house_expenses(id INTEGER PRIMARY KEY AUTOINCREMENT,household_id,expense_date,expense_type,description,amount,note);
    ''')
    class C:
        def __enter__(s): return s
        def __exit__(s,*a): raw.commit()
        def execute(s,sql,params=()):
            sql=sql.replace('%s','?')
            m=re.match(r'\s*ALTER TABLE (\w+) ADD COLUMN IF NOT EXISTS (\w+) (.+)',sql,re.I)
            if m:
                cols=[r[1] for r in raw.execute(f'PRAGMA table_info({m.group(1)})')]
                if m.group(2) in cols: return raw.execute('SELECT 1')
                sql=f'ALTER TABLE {m.group(1)} ADD COLUMN {m.group(2)} {m.group(3)}'
            if 'information_schema.columns' in sql:
                class R:
                    def __init__(s,rows): s.rows=rows
                    def fetchall(s): return s.rows
                return R([(t,r[1]) for t in params for r in raw.execute(f'PRAGMA table_info({t})')])
            return raw.execute(sql,tuple(params or ()))
        def commit(s): raw.commit()
    db.conn=lambda: C()
    db.user_has_feature=lambda *a,**k: True
    db.is_household_admin=lambda *a,**k: True
    db.ensure_schema()
    return db
