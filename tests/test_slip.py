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

def _env(**kw):
    for k in ('ANTHROPIC_API_KEY','GEMINI_API_KEY','SLIP_PROVIDER','GEMINI_MODEL'): os.environ.pop(k,None)
    os.environ.update(kw)

class _R:
    def __init__(s,status=200,body=None,text=''): s.status_code=status; s._b=body; s.text=text
    def json(s): return s._b

GOOD='{"is_slip":true,"amount":350,"date":"2026-11-04","receiver":"ร้าน ABC","bank":"SCB","memo":""}'
def gem(text=GOOD): return {'candidates':[{'content':{'parts':[{'text':text}]}}]}
def ant(text=GOOD): return {'content':[{'type':'text','text':text}]}

def test_free_mode_without_keys():
    _env(); assert not ai.slip_enabled() and ai.slip_providers()==[] and ai.parse_slip(b'\xff\xd8\xff1')['amount'] is None

def test_gemini_request_shape_and_result():
    _env(GEMINI_API_KEY='gk'); seen={}
    import requests
    def post(url,headers,json,timeout): seen.update(url=url,h=headers,b=json); return _R(200,gem())
    requests.post=post
    t=ai.parse_slip(b'\xff\xd8\xff\x00data')
    assert t['amount']==350 and t['merchant']=='ร้าน ABC' and ai.slip_providers()==['gemini']
    assert seen['url']=='https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent'
    assert seen['h']['x-goog-api-key']=='gk'
    parts=seen['b']['contents'][0]['parts']; assert parts[0]['inline_data']['mime_type']=='image/jpeg' and 'text' in parts[1]
    assert seen['b']['generationConfig']['responseMimeType']=='application/json'
    _env(GEMINI_API_KEY='gk',GEMINI_MODEL='gemini-3.5-flash-lite'); ai.parse_slip(b'\xff\xd8\xff')
    assert seen['url'].endswith('/models/gemini-3.5-flash-lite:generateContent')

def test_anthropic_only_still_works():
    _env(ANTHROPIC_API_KEY='ak'); seen={}
    import requests
    def post(url,headers,json,timeout): seen.update(url=url,h=headers,b=json); return _R(200,ant())
    requests.post=post
    assert ai.parse_slip(b'\xff\xd8\xff')['amount']==350 and seen['url']=='https://api.anthropic.com/v1/messages'
    assert seen['h']['x-api-key']=='ak' and seen['b']['messages'][0]['content'][0]['source']['media_type']=='image/jpeg'

def test_fallback_when_gemini_fails_but_not_when_unreadable():
    _env(GEMINI_API_KEY='gk',ANTHROPIC_API_KEY='ak'); calls=[]
    import requests
    def post(url,headers,json,timeout):
        calls.append('gemini' if 'googleapis' in url else 'anthropic')
        if 'googleapis' in url: return _R(429,text='quota')
        return _R(200,ant())
    requests.post=post
    assert ai.parse_slip(b'\xff\xd8\xff')['amount']==350 and calls==['gemini','anthropic']      # โควตา Gemini หมด → สลับ
    calls.clear()
    def post2(url,headers,json,timeout):
        calls.append('gemini' if 'googleapis' in url else 'anthropic'); return _R(200,gem('{"is_slip":false}'))
    requests.post=post2
    assert ai.parse_slip(b'\xff\xd8\xff')['amount'] is None and calls==['gemini']                 # ไม่ใช่สลิป → ไม่เรียกเจ้าสอง
    def boom(*a,**k): raise RuntimeError('net')
    requests.post=boom; assert ai.parse_slip(b'\xff\xd8\xff')['amount'] is None                     # ล้มทั้งคู่ → โหมดให้พิมพ์ยอด
    def blocked(*a,**k): return _R(200,{'candidates':[]})
    requests.post=blocked; calls.clear(); assert ai.parse_slip(b'\xff\xd8\xff')['amount'] is None

def test_provider_preference():
    _env(GEMINI_API_KEY='gk',ANTHROPIC_API_KEY='ak'); assert ai.slip_providers()==['gemini','anthropic']
    _env(GEMINI_API_KEY='gk',ANTHROPIC_API_KEY='ak',SLIP_PROVIDER='anthropic'); assert ai.slip_providers()==['anthropic']
    _env(ANTHROPIC_API_KEY='ak',SLIP_PROVIDER='gemini'); assert ai.slip_providers()==[]            # ระบุเจ้าที่ไม่มี key
    _env()

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
