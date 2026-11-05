import os, sys, types, asyncio, json
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0,ROOT)
import ai

def test_json_to_tx_basic_and_buddhist_year():
    t=ai.slip_from_json({'is_slip':True,'amount':'1,250.50','date':'2569-11-02','receiver':'นาย สมชาย ใ','bank':'KBank','memo':'ค่าไฟ'},'2026-11-05')
    assert t['amount']==1250.5 and t['occurred_at']=='2026-11-02' and t['type']=='expense'
    assert 'KBank' in t['note'] and t['merchant']=='นาย สมชาย ใ' and t['category']=='บิล/ค่าสาธารณูปโภค'

def test_rejects_bad_data():
    today='2026-11-05'
    for bad in (None,'x',{'is_slip':False,'amount':100},{'is_slip':True,'amount':None},{'is_slip':True,'amount':'abc'},
                {'is_slip':True,'amount':0},{'is_slip':True,'amount':-5},{'is_slip':True,'amount':99999999}):
        assert ai.slip_from_json(bad,today)['amount'] is None, bad

def test_implausible_dates_fall_back_to_today():
    for d in ('2031-01-01','1999-01-01','not-a-date',None,'2026-13-45'):
        assert ai.slip_from_json({'is_slip':True,'amount':10,'date':d},'2026-11-05')['occurred_at']=='2026-11-05',d

def test_extract_json_from_fenced_text():
    assert ai._extract_json('```json\n{"is_slip": true, "amount": 5}\n```')=={'is_slip':True,'amount':5}
    assert ai._extract_json('no json') is None and ai._extract_json('{bad') is None

def test_parse_slip_request_shape_and_free_mode():
    os.environ.pop('ANTHROPIC_API_KEY',None)
    assert not ai.slip_enabled() and ai.parse_slip(b'\xff\xd8\xff123')['amount'] is None   # ไม่มี key = โหมดฟรี ไม่เรียก API
    os.environ['ANTHROPIC_API_KEY']='k'; seen={}
    import requests
    class R:
        status_code=200
        def json(s): return {'content':[{'type':'text','text':'{"is_slip":true,"amount":350,"date":"2026-11-04","receiver":"ร้าน ABC","bank":"SCB","memo":""}'}]}
    def post(url,headers,json,timeout): seen.update(url=url,headers=headers,body=json,timeout=timeout); return R()
    requests.post=post
    t=ai.parse_slip(b'\xff\xd8\xff\x00data')
    assert t['amount']==350 and t['merchant']=='ร้าน ABC'
    assert seen['url']=='https://api.anthropic.com/v1/messages' and seen['headers']['x-api-key']=='k' and 'anthropic-version' in seen['headers']
    blk=seen['body']['messages'][0]['content']; assert blk[0]['type']=='image' and blk[0]['source']['media_type']=='image/jpeg' and blk[1]['type']=='text'
    class E(R):
        status_code=500; text='boom'
    requests.post=lambda *a,**k:E(); assert ai.parse_slip(b'\xff\xd8\xff')['amount'] is None
    def boom(*a,**k): raise RuntimeError('net')
    requests.post=boom; assert ai.parse_slip(b'\xff\xd8\xff')['amount'] is None
    os.environ.pop('ANTHROPIC_API_KEY')

def test_handle_slip_flow_dedupe_and_limit():
    # โหลด app.py แบบ stub (ไม่มี fastapi/ฐานข้อมูลในเครื่องทดสอบ)
    class Dummy(types.ModuleType):
        def __getattr__(s,n):
            if n.startswith('__'): raise AttributeError(n)
            return lambda *a,**k: Dummy('x') if False else None
    fa=types.ModuleType('fastapi')
    class FastAPI:
        def __init__(s,*a,**k): pass
        def _d(s,*a,**k): return lambda f:f
        get=post=put=delete=patch=api_route=on_event=_d
        def add_middleware(s,*a,**k): pass
        def mount(s,*a,**k): pass
    fa.FastAPI=FastAPI; fa.Request=object; fa.HTTPException=type('HTTPException',(Exception,),{'__init__':lambda s,status_code=0,detail='':None})
    fr=types.ModuleType('fastapi.responses'); fr.FileResponse=fr.JSONResponse=fr.Response=lambda *a,**k:None
    sys.modules.update({'fastapi':fa,'fastapi.responses':fr})
    for n in ('psycopg2','psycopg2.extras'): sys.modules[n]=types.ModuleType(n)
    sys.modules['psycopg2'].IntegrityError=Exception; sys.modules['psycopg2'].extras=sys.modules['psycopg2.extras']; sys.modules['psycopg2.extras'].DictCursor=object
    for n in ('dotenv',):
        m=types.ModuleType(n); m.load_dotenv=lambda *a,**k:None; sys.modules[n]=m
    dbm=Dummy('database'); sys.modules['database']=dbm
    os.environ['LINE_CHANNEL_SECRET']='s'
    import importlib; sys.modules.pop('app',None); app=importlib.import_module('app')
    sent=[]; seen=set(); saved=[]
    app.reply=lambda tok,msgs: sent.append(' | '.join(m.get('text','FLEX') for m in msgs))
    app.get_line_content=lambda mid: b'\xff\xd8\xff'+mid.encode()
    app.active_scope=lambda u:({'members':[]},1)
    app.reminder_seen=lambda k:k in seen; app.reminder_mark=lambda k:seen.add(k)
    app.add_transaction=lambda **kw:(saved.append(kw) or {'id':1,**kw}); app.transaction_flex=lambda *a:{'type':'flex'}; app.notify_transaction=lambda *a:None
    app.parse_slip=lambda c: {'type':'expense','amount':350.0,'category':'อื่นๆ','merchant':'ABC','note':'สลิป','occurred_at':'2026-11-04'}
    ev={'replyToken':'t'}; run=lambda mid:asyncio.run(app.handle_slip(ev,'U1',{'id':mid}))
    run('a'); assert len(saved)==1 and saved[0]['source']=='slip' and saved[0]['amount']==350.0 and sent[-1].startswith('FLEX | 🧾 อ่านจากสลิปอัตโนมัติ') and 'ลบรายการล่าสุด' in sent[-1]
    run('a'); assert len(saved)==1 and 'บันทึกไปแล้ว' in sent[-1]                      # รูปซ้ำ ไม่บันทึกซ้ำ
    app.parse_slip=lambda c:{'type':'expense','amount':None,'category':'อื่นๆ','merchant':'','note':'','occurred_at':'2026-11-04'}
    run('b'); assert len(saved)==1 and 'อ่านยอดจากรูปนี้ไม่ได้' in sent[-1]
    run('b'); assert len(saved)==1 and 'อ่านยอดจากรูปนี้ไม่ได้' in sent[-1]               # ล้มเหลว ไม่ถูกมาร์กว่าบันทึกแล้ว → ส่งใหม่ได้
    app.SLIP_DAILY_LIMIT=2; run('c'); assert 'ครบ 2 รูป' in sent[-1]                       # a,b(สำเร็จนับ),b(ซ้ำไม่นับ?) ถึงลิมิต

if __name__=='__main__':
    for k,v in list(globals().items()):
        if k.startswith('test_'): v(); print('ok',k)
