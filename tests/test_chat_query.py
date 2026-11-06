import os, sys
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0,ROOT)
import harness
from datetime import date
harness.load()                      # ติดตั้ง database จำลองก่อน import chat_query
from chat_query import classify, period_range

def test_classify_spend_questions():
    c=lambda t: classify(t)
    assert c('เดือนนี้ใช้ไปเท่าไหร่')==('spend',{'period':'month','type':'expense','category':None})
    assert c('ค่ากินเดือนนี้')==None                      # ไม่มีคำถาม/สรุป → ไม่ใช่คำถาม (กันชนกับการบันทึก)
    assert c('ค่ากินเดือนนี้เท่าไหร่')==('spend',{'period':'month','type':'expense','category':'อาหาร'})
    assert c('สัปดาห์ที่แล้วใช้เท่าไหร่')[1]['period']=='last_week' and c('เมื่อวานจ่ายไปเท่าไร')[1]['period']=='yesterday'
    assert c('เดือนนี้รายรับเท่าไหร่')[1]['type']=='income' and c('เดือนที่แล้วเหลือเท่าไหร่')[1]['type']=='balance'
    assert c('ค่าน้ำมันเดือนนี้ใช้เท่าไหร่')[1]['category']=='เดินทาง' and c('ค่าน้ำเดือนนี้รวมเท่าไหร่')[1]['category']=='บิล/ค่าสาธารณูปโภค'

def test_classify_does_not_hijack_entries_or_commands():
    for t in ['กินข้าว 120','เดือนนี้','สรุป','ซื้อกาแฟวันนี้ 65','ค่ากินเดือนนี้ 3000','บ้าน ค่าน้ำ 320','ลบ 12','วันนี้กินข้าว','ผ่อน เครื่องซักผ้า 1500']:
        assert classify(t) is None, t

def test_classify_edit_and_tax():
    assert classify('แก้ 123 150')==('edit',{'id':123,'amount':150.0,'category':None})
    assert classify('แก้ล่าสุด 1,250.50 หมวด อาหาร')==('edit',{'id':None,'amount':1250.5,'category':'อาหาร'})
    assert classify('แก้ 5 หมวด เดินทาง')==('edit',{'id':5,'amount':None,'category':'เดินทาง'})
    assert 'ไม่รู้จักหมวด' in classify('แก้ 5 หมวด xyz')[1]['error'] and classify('แก้ล่าสุด')is None
    assert classify('สรุปดอกเบี้ยบ้าน')==('tax',{'year':None,'share':1})
    assert classify('สรุปดอกเบี้ยบ้าน 2569 หาร 2')==('tax',{'year':2026,'share':2})
    assert classify('ดอกเบี้ยบ้านปี 2026')==('tax',{'year':2026,'share':1}) and classify('ลดหย่อนภาษีดอกเบี้ยบ้าน')[0]=='tax'
    assert classify('ดอกเบี้ยบ้าน 5000') is None                    # ยอดเงิน = รายการบันทึก ไม่ใช่ปีภาษี

def test_period_ranges():
    t=date(2026,11,6)   # วันศุกร์
    assert period_range('week',t)==(date(2026,11,2),t) and period_range('last_week',t)==(date(2026,10,26),date(2026,11,1))
    assert period_range('last_month',t)==(date(2026,10,1),date(2026,10,31)) and period_range('month',t)==(date(2026,11,1),t)

def _setup():
    db=harness.load(); sys.modules['database']=db
    import chat_query; chat_query.db=db
    for u,t,a,c,d in (('A','expense',120,'อาหาร','2026-11-05T12:00:00'),('A','expense',80,'อาหาร','2026-11-06T08:00:00'),('B','expense',500,'เดินทาง','2026-11-03T09:00:00'),
                      ('A','expense',300,'อาหาร','2026-10-02T09:00:00'),('A','income',30000,'เงินเดือน','2026-11-01T09:00:00'),('A','expense',999,'ช้อปปิ้ง','2026-09-30T09:00:00')):
        db.add_transaction(user_id=u,type=t,amount=a,category=c,occurred_at=d,household_id=1,note='x')
    return db,chat_query

def test_spend_replies():
    db,cq=_setup(); today=date(2026,11,6)
    r=cq.run('spend',{'period':'month','type':'expense','category':None},'A',None,1,today)
    assert '700 บาท · 3 รายการ' in r and 'เดินทาง 500' in r and 'อาหาร 200' in r and 'ช่วงเดียวกันเดือนก่อน 300' in r, r
    r=cq.run('spend',{'period':'month','type':'expense','category':'อาหาร'},'A',None,1,today); assert 'หมวด อาหาร 200 บาท · 2 รายการ' in r, r
    r=cq.run('spend',{'period':'today','type':'expense','category':None},'A',None,1,today); assert '80 บาท' in r
    r=cq.run('spend',{'period':'month','type':'balance','category':None},'A',None,1,today); assert 'คงเหลือ 29,300' in r, r
    r=cq.run('spend',{'period':'yesterday','type':'expense','category':'เดินทาง'},'A',None,1,today); assert 'ยังไม่มี' in r

def test_edit_amount_category_and_permissions():
    db,cq=_setup()
    tx=db.add_transaction(user_id='A',type='expense',amount=120,category='อื่นๆ',household_id=1,note='กินข้าว',occurred_at='2026-11-06T10:00:00')
    r=cq.run('edit',{'id':tx['id'],'amount':150.0,'category':None},'A',None,1); assert '120 → 150' in r, r
    row=db.get_recent(1,household_id=1)[0]; assert row['amount']==150.0 and json_loads(row['split_amounts'])=={'A':150.0}
    r=cq.run('edit',{'id':tx['id'],'amount':None,'category':'อาหาร'},'A',None,1); assert 'อื่นๆ → อาหาร' in r
    db.is_household_admin=lambda *a,**k:False
    r=cq.run('edit',{'id':tx['id'],'amount':1.0,'category':None},'B',None,1); assert 'เฉพาะรายการของตัวเอง' in r      # คนอื่นแก้ไม่ได้
    assert cq.run('edit',{'id':9999,'amount':1.0,'category':None},'A',None,1).endswith('ไม่พบรายการนี้')
    assert 'ยอดไม่ถูกต้อง' in cq.run('edit',{'id':tx['id'],'amount':-5.0,'category':None},'A',None,1)
    r=cq.run('edit',{'id':None,'amount':77.0,'category':None},'A',None,1); assert '→ 77' in r                      # แก้ล่าสุด
    db.is_household_admin=lambda *a,**k:True

def test_edit_split_keeps_proportions():
    db,cq=_setup()
    tx=db.add_transaction(user_id='A',type='expense',amount=300,category='อาหาร',household_id=1,payer_user_id='A',split_mode='equal',split_participants=['A','B','C'],occurred_at='2026-11-06T10:00:00')
    row,err=db.update_transaction(tx['id'],'A',1,amount=100.0); assert not err
    am=json_loads(row['split_amounts']); assert round(sum(am.values()),2)==100.0 and len(am)==3, am

def test_tax_by_year():
    db,cq=_setup()
    db.save_mortgage('u',1,{'loan_amount':3160000,'start_date':'2025-07-20','term_years':30,'monthly_payment':6600,'payment_day':3,'rates':[{'start_date':'2025-07-20','end_date':'','rate_type':'fixed','rate_percent':2.1}]})
    for amt,d in ((19600,'2025-07-31'),(16000,'2025-08-31'),(15600,'2025-10-03'),(10000,'2025-11-03'),(10000,'2025-12-03'),(10000,'2026-01-03'),(10000,'2026-02-03')): db.add_mortgage_payment('u',1,{'amount':amt,'payment_date':d})
    m=db.get_mortgage(1); rows=db.mortgage_interest_by_year(m,date(2026,11,6))
    y25=[r for r in rows if r['year']==2025][0]; y26=[r for r in rows if r['year']==2026][0]
    assert y25['count']==5 and y25['interest']>1999.89+5604.66+5946.52 and y25['maybe_incomplete']      # เริ่มกู้ ก.ค. ควรมี 6 งวด แต่บันทึก 3 → เตือนว่าอาจไม่ครบ
    assert y26['count']==2 and not y26['maybe_incomplete'] and y26.get('projected_interest',0)>y26['interest']        # ปีปัจจุบัน: ไม่เตือน + มีประมาณการทั้งปี
    r=cq.run('tax',{'year':2025,'share':1},'A',None,1,date(2026,11,6))
    assert 'ปี 2568' in r and '5 งวด' in r and 'ลดหย่อนได้' in r and 'ตรวจว่าบันทึกครบ' in r, r
    r2=cq.run('tax',{'year':2025,'share':2},'A',None,1,date(2026,11,6)); assert 'กู้ร่วม 2 คน' in r2
    db.user_has_feature=lambda *a,**k:False
    assert cq.run('tax',{'year':2025,'share':1},'A',None,1,date(2026,11,6)) is None        # ไม่มีสิทธิ์ → เงียบ
    db.user_has_feature=lambda *a,**k:True
    assert 'ไม่มีงวดที่บันทึกในปี 2030' in cq.run('tax',{'year':2030,'share':1},'A',None,1,date(2026,11,6))

def test_tax_cap_and_opening_balance_flags():
    db,cq=_setup()
    m={'loan_amount':5000000,'start_date':'2024-01-01','payment_day':1,'term_years':30,'monthly_payment':30000,'rates':[],
       'payments':[{'id':1,'payment_date':'2025-03-01','amount':120000,'principal':10000,'interest':110000,'extra_principal':0}],
       'opening_balance':4000000,'opening_date':'2024-12-31'}
    r=db.mortgage_interest_by_year(m,date(2026,11,6))[0]
    assert r['over_limit'] and r['deductible']==100000.0 and r['partial_start'] is False      # ยอดยกมาสิ้นปีก่อน → ปี 2025 ครบ
    m['opening_date']='2025-02-01'
    assert db.mortgage_interest_by_year(m,date(2026,11,6))[0]['partial_start'] is True        # ยอดยกมากลางปี → เตือนว่านับไม่ครบปี

import json
json_loads=json.loads
if __name__=='__main__':
    for k,v in list(globals().items()):
        if k.startswith('test_'): v(); print('ok',k)
