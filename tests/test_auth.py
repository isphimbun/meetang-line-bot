import os, sys, json, asyncio, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ['DASH_SECRET']='test-secret-123'
import auth

async def call(mw, method, path, qs='', headers=None, body=b''):
    seen={}
    async def app(scope, receive, send):
        msg=await receive(); seen['qs']=scope['query_string'].decode(); seen['body']=msg.get('body',b'')
        await send({'type':'http.response.start','status':200,'headers':[]}); await send({'type':'http.response.body','body':b'ok'})
    out={}
    async def send(m):
        if m['type']=='http.response.start': out['status']=m['status']
    sent=[False]
    async def receive():
        if not sent[0]: sent[0]=True; return {'type':'http.request','body':body,'more_body':False}
        return {'type':'http.disconnect'}
    scope={'type':'http','method':method,'path':path,'query_string':qs.encode(),'headers':headers or []}
    await auth.AuthMiddleware(app)(scope,receive,send)
    return out.get('status'),seen

def run(c): return asyncio.run(c)

def test_token_roundtrip_and_kinds():
    t=auth.make_token('Uabc','session'); assert auth.verify_token(t,'session')=='Uabc'
    assert auth.verify_token(t,'login') is None                        # session ใช้เป็น login ไม่ได้
    l=auth.make_token('Uabc','login'); assert auth.verify_token(l,'session') is None
    assert auth.verify_token(t[:-2]+'xx','session') is None            # ลายเซ็นผิด
    assert auth.verify_token('garbage','session') is None
    old=auth.make_token('Uabc','session',ttl=-5); assert auth.verify_token(old,'session') is None

def test_middleware_blocks_and_forces_identity():
    mw=None
    st,_=run(call(mw,'GET','/api/loan','user_id=Uvictim&household_id=1'))
    assert st==401
    tok=auth.make_token('Ume','session'); h=[(b'authorization',f'Bearer {tok}'.encode())]
    st,seen=run(call(mw,'GET','/api/loan','user_id=Uvictim&household_id=1',h))
    assert st==200 and 'user_id=Ume' in seen['qs'] and 'Uvictim' not in seen['qs'] and 'household_id=1' in seen['qs']
    h2=h+[(b'content-type',b'application/json')]
    st,seen=run(call(mw,'POST','/api/loan/payment','',h2,json.dumps({'user_id':'Uvictim','amount':5}).encode()))
    assert json.loads(seen['body'])=={'user_id':'Ume','amount':5}

def test_public_paths_and_static_pass():
    st,_=run(call(None,'POST','/api/auth/exchange')); assert st==200
    st,_=run(call(None,'GET','/')); assert st==200
    st,_=run(call(None,'GET','/webhook')); assert st==200

def test_disabled_when_no_secret():
    os.environ.pop('DASH_SECRET'); os.environ.pop('LINE_CHANNEL_SECRET',None)
    assert not auth.auth_enabled(); st,_=run(call(None,'GET','/api/loan','user_id=x')); assert st==200
    os.environ['DASH_SECRET']='test-secret-123'

if __name__=='__main__':
    for k,v in list(globals().items()):
        if k.startswith('test_'): v(); print('ok',k)
