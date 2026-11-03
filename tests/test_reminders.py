import harness, sys, types
from datetime import date

def test_mortgage_reminder_and_dedupe():
    db=harness.load()
    store=set(); db.reminder_seen=lambda k:k in store; db.reminder_mark=lambda k:store.add(k)
    db.list_loan_household_ids=lambda:[1]
    sent=[]
    sys.modules.pop('reminders',None)
    import notify; notify._send=lambda ids,msgs:sent.append(msgs[0]['altText'])
    notify.get_household=lambda hid:{'id':1,'name':'TangTar','members':[{'user_id':'A','display_name':'a'}]}
    notify.user_has_feature=lambda *a,**k:True
    import reminders
    reminders.db=db; reminders.broadcast=lambda hid,feat,build: sent.append((feat,build({'name':'TangTar'})['altText']))
    db.save_mortgage('u',1,{'loan_amount':3160000,'start_date':'2026-07-20','term_years':30,'monthly_payment':6600,'payment_day':3,
        'rates':[{'start_date':'2026-07-20','end_date':'2029-07-19','rate_type':'fixed','rate_percent':2.1,'label':'ปี1-3'},{'start_date':'2029-07-20','end_date':'','rate_type':'mrr','mrr_offset':-1.5,'label':'MRR','mrr_offset':-1.5}],'current_mrr':7.0})
    reminders.run_once(date(2026,8,1))        # due 3 ส.ค. → อีก 2 วัน ไม่เตือน
    assert sent==[], sent
    reminders.run_once(date(2026,8,2))        # พรุ่งนี้
    assert len(sent)==1 and 'พรุ่งนี้' in sent[0][1] and sent[0][0]=='loan', sent
    reminders.run_once(date(2026,8,2)); assert len(sent)==1   # ไม่ซ้ำ
    db.add_mortgage_payment('u',1,{'amount':9000,'payment_date':'2026-08-01'})   # จ่ายก่อนกำหนดแล้ว
    n=len(sent); reminders.run_once(date(2026,8,3)); assert len(sent)==n          # ไม่เตือนงวดที่จ่ายแล้ว
    reminders.run_once(date(2029,7,13)); assert any('อัตราดอกเบี้ย' in s[1] for s in sent), sent

if __name__=='__main__':
    test_mortgage_reminder_and_dedupe(); print('ok reminders')
