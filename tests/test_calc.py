"""รัน: python tests/test_calc.py  (ไม่ต้องมีฐานข้อมูล ใช้ sqlite จำลองใน harness.py)"""
import harness

def fresh():
    return harness.load()

def mortgage(db, **kw):
    d={'property_name':'บ้าน','loan_amount':3160000,'start_date':'2026-07-20','term_years':30,'monthly_payment':6600,'payment_day':3,
       'rates':[{'start_date':'2026-07-20','end_date':'2029-07-19','rate_type':'fixed','rate_percent':2.1}]}
    d.update(kw); return db.save_mortgage('u',1,d)

def test_user_real_example():
    db=fresh(); mortgage(db)
    for amt,d in ((19600,'2026-07-31'),(16000,'2026-08-31'),(15600,'2026-10-03')): m=db.add_mortgage_payment('u',1,{'amount':amt,'payment_date':d})
    got=[(p['principal'],p['interest']) for p in m['payments']]
    assert got==[(17600.11,1999.89),(10395.34,5604.66),(9653.48,5946.52)],got

def test_rounding_half_up_and_basis():
    db=fresh()
    assert db.accrue_interest(3000000,'2026-01-01','2026-02-01',lambda d:3.5)==8917.81
    assert db.accrue_interest(3000000,'2026-02-01','2026-03-01',lambda d:3.5)==8054.79
    assert db.accrue_interest(1000000,'2028-02-01','2028-03-01',lambda d:3.65)==2900.00          # 365
    assert db.accrue_interest(1000000,'2028-02-01','2028-03-01',lambda d:3.65,'360')==2940.28     # 360
    assert db.accrue_interest(1000000,'2028-02-01','2028-03-01',lambda d:3.66,'act')==2900.00     # 29/366*3.66%

def test_rate_change_inside_period_uses_daily_boundary():
    db=fresh()
    m={'rates':[{'start_date':'2026-01-01','end_date':'2026-12-31','rate_type':'fixed','rate_percent':2.0},
                {'start_date':'2027-01-01','end_date':'','rate_type':'fixed','rate_percent':5.0}]}
    assert db._mort_interest(m,1000000,'2026-12-20','2027-01-10')==1890.41
    # เปลี่ยนอัตรากลางเดือน: 20 วันแรก 2% อีก 11 วัน 5%
    m2={'rates':[{'start_date':'2026-01-01','end_date':'2026-01-20','rate_type':'fixed','rate_percent':2.0},
                 {'start_date':'2026-01-21','end_date':'','rate_type':'fixed','rate_percent':5.0}]}
    assert db._mort_interest(m2,1000000,'2026-01-01','2026-02-01')==round(1000000*0.02*20/365+1000000*0.05*11/365,2)

def test_rate_gap_falls_back_to_last_period_not_zero():
    db=fresh(); m=mortgage(db)
    assert db._rate_for_date(m,'2031-01-01')==2.1

def test_opening_balance():
    db=fresh(); m=mortgage(db,opening_balance=3000000,opening_date='2026-09-03')
    assert m['opening_balance']==3000000
    m=db.add_mortgage_payment('u',1,{'amount':10000,'payment_date':'2026-10-03'})
    p=m['payments'][0]; assert p['interest']==round(3000000*0.021*30/365,2),p   # 30 วัน
    try: db.add_mortgage_payment('u',1,{'amount':1,'payment_date':'2026-08-01'}); assert False
    except ValueError: pass

def test_recalc_keeps_manual_rows():
    db=fresh(); mortgage(db)
    db.add_mortgage_payment('u',1,{'amount':19600,'payment_date':'2026-07-31','interest':2000.50})   # กรอกจากใบแจ้งหนี้
    m=db.add_mortgage_payment('u',1,{'amount':16000,'payment_date':'2026-08-31'})
    r=db.recalc_mortgage_payments('u',1)
    assert r['skipped_manual']==1 and r['updated']==1
    m=db.get_mortgage(1); assert m['payments'][0]['interest']==2000.5

def test_same_day_two_payments():
    db=fresh(); mortgage(db)
    db.add_mortgage_payment('u',1,{'amount':10000,'payment_date':'2026-08-03'})
    m=db.add_mortgage_payment('u',1,{'amount':10000,'payment_date':'2026-08-03'})
    assert m['payments'][1]['interest']==0.0

def test_stalled_forecast_is_flagged():
    db=fresh(); m=mortgage(db,monthly_payment=3000)
    f=db.mortgage_forecast(m,360); assert f[-1].get('stalled') and len(f)<=13

def test_installment_interest_types():
    db=fresh()
    for t,rate,exp_int in (('none',10,0),('flat',12,100.0)):
        db.add_installment('u',1,{'name':t,'financed_amount':10000,'total_installments':10,'monthly_payment':1100,'start_date':'2026-01-01','interest_rate':rate,'interest_type':t})
    plans=db.get_installments(1)
    none=[p for p in plans if p['name']=='none'][0]; flat=[p for p in plans if p['name']=='flat'][0]
    p=db.add_installment_payment('u',1,{'plan_id':none['id'],'amount':1000,'payment_date':'2026-02-01'})
    p=db.add_installment_payment('u',1,{'plan_id':flat['id'],'amount':1100,'payment_date':'2026-02-01'})
    f=[x for x in p if x['name']=='flat'][0]['payments'][0]; assert (f['principal'],f['interest'])==(1000.0,100.0),f
    db.add_installment('u',1,{'name':'red','financed_amount':12000,'total_installments':12,'monthly_payment':1100,'start_date':'2026-01-01','interest_rate':6,'interest_type':'reducing'})
    rid=[x for x in db.get_installments(1) if x['name']=='red'][0]['id']
    p=db.add_installment_payment('u',1,{'plan_id':rid,'amount':1100,'payment_date':'2026-02-01'})
    r=[x for x in p if x['name']=='red'][0]; assert r['payments'][0]['interest']==round(12000*0.06*31/365,2) and r['remaining']<12000

def test_insurance_daily_interest():
    db=fresh(); mortgage(db)
    ins=db.save_house_insurance('u',1,{'insurance_type':'MRTA','payment_method':'ผ่อนแยก','financed_amount':60000,'financed_installments':12,'financed_monthly_payment':5200,'financed_start_date':'2026-08-03','financed_payment_day':3,'rate_mode':'custom','rate_percent':3,'amount':60000})
    r=db.add_house_insurance_payment('u',1,{'insurance_id':ins['id'],'payment_date':'2026-09-03','amount':5200})
    assert r['payments'][0]['interest']==round(60000*0.03*31/365,2)

if __name__=='__main__':
    n=0
    for k,v in list(globals().items()):
        if k.startswith('test_'): v(); n+=1; print('ok',k)
    print(n,'tests passed')
