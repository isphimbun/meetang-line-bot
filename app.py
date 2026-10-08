import os, json, base64, hashlib, hmac, shutil
from datetime import datetime
from zoneinfo import ZoneInfo
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse, JSONResponse
import requests

from database import (init_db, upsert_user, create_household, join_household, get_active_household,
                      get_user_households, set_active_household, add_transaction, get_summary, get_recent,
                      get_commands, add_command, update_command, delete_command, find_command,
                      get_categories, delete_transaction, set_display_name, get_household, get_settlement,
                      rename_household, delete_household, leave_household, is_household_admin,
                      get_member_permissions, set_member_features, set_member_role, user_has_feature, get_mortgage, is_super_admin, get_global_feature_permissions, set_global_feature, is_super_admin, get_global_feature_permissions, set_global_feature, global_user_has_feature, save_mortgage, add_mortgage_payment, mortgage_forecast, get_house_insurance,
    insurance_forecast, add_house_insurance_payment, add_house_insurance, get_house_expenses, add_house_expense, get_installments, add_installment, add_installment_payment, update_mortgage_payment, delete_mortgage_payment, update_house_insurance_payment, delete_house_insurance_payment)
from ai import parse_text, parse_slip
from split_utils import parse_split_instruction
from flex import summary_flex, transaction_flex, recent_flex, settlement_flex, household_flex, help_text

TZ = ZoneInfo(os.getenv('TZ', 'Asia/Bangkok'))
LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET', '')
LINE_ACCESS_TOKEN = os.getenv('LINE_ACCESS_TOKEN', '') or os.getenv('LINE_CHANNEL_ACCESS_TOKEN', '')
app = FastAPI(title='MeeTang LINE Bot')
init_db()


def setup_rich_menu_on_startup():
    """Create a fresh MeeTang Rich Menu on every deploy/startup and make it the default."""
    if not LINE_ACCESS_TOKEN:
        print('Rich Menu: skipped (LINE access token is missing)')
        return
    image_path = os.path.join(os.path.dirname(__file__), 'rich_menu.png')
    if not os.path.exists(image_path):
        print('Rich Menu: skipped (rich_menu.png is missing)')
        return

    headers = {'Authorization': f'Bearer {LINE_ACCESS_TOKEN}'}
    try:
        menu_data = {
            'size': {'width': 2500, 'height': 1686},
            'selected': True,
            'name': 'MeeTang Main Menu v29 Dashboard',
            'chatBarText': '💰 มีตังค์',
            'areas': [
                {'bounds': {'x': 0, 'y': 0, 'width': 833, 'height': 843},
                 'action': {'type': 'message', 'text': 'เพิ่มรายการ'}},
                {'bounds': {'x': 833, 'y': 0, 'width': 834, 'height': 843},
                 'action': {'type': 'message', 'text': 'รายการล่าสุด'}},
                {'bounds': {'x': 1667, 'y': 0, 'width': 833, 'height': 843},
                 'action': {'type': 'message', 'text': 'สรุปเดือนนี้'}},
                {'bounds': {'x': 0, 'y': 843, 'width': 833, 'height': 843},
                 'action': {'type': 'message', 'text': 'บ้านของฉัน'}},
                {'bounds': {'x': 833, 'y': 843, 'width': 834, 'height': 843},
                 'action': {'type': 'message', 'text': 'เคลียร์ยอด'}},
                {'bounds': {'x': 1667, 'y': 843, 'width': 833, 'height': 843},
                 'action': {'type': 'uri', 'uri': os.getenv('DASHBOARD_URL', 'https://meetang-bot.onrender.com')}},
            ]
        }

        # Always create a NEW menu. The old v5 menu is intentionally not reused.
        r = requests.post(
            'https://api.line.me/v2/bot/richmenu',
            headers={**headers, 'Content-Type': 'application/json'},
            json=menu_data,
            timeout=30
        )
        r.raise_for_status()
        menu_id = r.json()['richMenuId']

        # Upload the new artwork.
        with open(image_path, 'rb') as f:
            r = requests.post(
                f'https://api-data.line.me/v2/bot/richmenu/{menu_id}/content',
                headers={**headers, 'Content-Type': 'image/png'},
                data=f,
                timeout=60
            )
        r.raise_for_status()

        # Make this new menu the default for all users.
        r = requests.post(
            f'https://api.line.me/v2/bot/user/all/richmenu/{menu_id}',
            headers=headers,
            timeout=30
        )
        r.raise_for_status()

        print('Rich Menu v29 activated:', menu_id)
    except Exception as e:
        print('Rich Menu setup error:', repr(e))


@app.on_event('startup')
async def startup_tasks():
    setup_rich_menu_on_startup()


def verify_signature(body: bytes, signature: str) -> bool:
    if not LINE_CHANNEL_SECRET: return True
    digest = hmac.new(LINE_CHANNEL_SECRET.encode(), body, hashlib.sha256).digest()
    return hmac.compare_digest(base64.b64encode(digest).decode(), signature or '')


def line_headers(): return {'Authorization': f'Bearer {LINE_ACCESS_TOKEN}', 'Content-Type': 'application/json'}

def reply(reply_token, messages):
    if not LINE_ACCESS_TOKEN: return
    r = requests.post('https://api.line.me/v2/bot/message/reply', headers=line_headers(), json={'replyToken': reply_token, 'messages': messages}, timeout=20)
    r.raise_for_status()

def get_line_content(message_id: str) -> bytes:
    r = requests.get(f'https://api-data.line.me/v2/bot/message/{message_id}/content', headers={'Authorization': f'Bearer {LINE_ACCESS_TOKEN}'}, timeout=30)
    r.raise_for_status(); return r.content

def active_scope(user_id):
    h = get_active_household(user_id)
    return h, (h['id'] if h else None)

def help_message():
    return help_text()

@app.get('/')
def root(): return FileResponse('static/index.html')

@app.get('/api/backup/database')
def backup_database():
    # MeeTang now uses Supabase PostgreSQL; the old SQLite-file backup endpoint is intentionally disabled.
    raise HTTPException(status_code=410, detail='MeeTang database is now stored in Supabase PostgreSQL')

@app.get('/api/backup/status')
def backup_status():
    return {'ok': True, 'database': 'supabase_postgresql', 'database_configured': bool(os.getenv('DATABASE_URL'))}

@app.get('/health')
def health(): return {'ok': True, 'service': 'moneymate-line-bot', 'multi_user': True, 'shared_household': True}

@app.get('/api/summary')
def api_summary(month: str | None = None, user_id: str | None = None, household_id: int | None = None):
    return get_summary(month, user_id=user_id, household_id=household_id)

@app.get('/api/recent')
def api_recent(limit: int = 30, user_id: str | None = None, household_id: int | None = None):
    return get_recent(limit, user_id=user_id, household_id=household_id)

@app.get('/api/categories')
def api_categories(): return get_categories()

@app.get('/api/households')
def api_households(user_id: str):
    hs = get_user_households(user_id)
    active = get_active_household(user_id)
    return {'households': hs, 'active_household_id': active['id'] if active else None}

@app.post('/api/households/create')
async def api_create_household(request: Request):
    data = await request.json()
    user_id = str(data.get('user_id') or '').strip()
    name = str(data.get('name') or '').strip()
    if not user_id or not name:
        raise HTTPException(status_code=400, detail='user_id and name are required')
    return create_household(user_id, name)

@app.post('/api/households/switch')
async def api_switch_household(request: Request):
    data = await request.json()
    user_id = str(data.get('user_id') or '').strip()
    household_id = int(data.get('household_id') or 0)
    ok = bool(user_id and household_id and set_active_household(user_id, household_id))
    return {'ok': ok, 'active': get_active_household(user_id) if ok else None}

@app.post('/api/households/rename')
async def api_rename_household(request: Request):
    data = await request.json()
    user_id = str(data.get('user_id') or '').strip()
    household_id = int(data.get('household_id') or 0)
    name = str(data.get('name') or '').strip()
    ok = bool(user_id and household_id and name and rename_household(user_id, household_id, name))
    return {'ok': ok, 'households': get_user_households(user_id)}

@app.delete('/api/households/{household_id}')
async def api_delete_household(household_id: int, user_id: str):
    deleted = delete_household(user_id, household_id)
    return {'ok': bool(deleted), 'deleted': deleted}

@app.get('/api/households/{household_id}')
def api_household(household_id: int, user_id: str):
    h = get_household(household_id)
    if not h or not any(m['user_id'] == user_id for m in h.get('members', [])):
        raise HTTPException(status_code=403, detail='not a household member')
    return h

@app.delete('/api/transactions/{tx_id}')
def api_delete(tx_id: int, user_id: str | None = None, household_id: int | None = None):
    return {'deleted': delete_transaction(tx_id, user_id=user_id, household_id=household_id)}

@app.get('/api/commands')
def api_commands(user_id: str, household_id: int | None = None):
    hid = household_id or (get_active_household(user_id) or {}).get('id')
    if not hid or not is_household_admin(user_id, int(hid)):
        raise HTTPException(status_code=403, detail='admin only')
    return {'commands': get_commands(), 'is_admin': True}

@app.post('/api/commands')
def api_add_command(payload: dict):
    user_id = str(payload.get('user_id') or '').strip(); hid = int(payload.get('household_id') or 0)
    if not user_id or not hid or not is_household_admin(user_id, hid): raise HTTPException(status_code=403, detail='admin only')
    try:
        return add_command(payload.get('name',''), payload.get('aliases',''), payload.get('action','custom'), payload.get('description',''), bool(payload.get('enabled',True)))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.put('/api/commands/{command_id}')
def api_update_command(command_id: int, payload: dict):
    user_id = str(payload.get('user_id') or '').strip(); hid = int(payload.get('household_id') or 0)
    if not user_id or not hid or not is_household_admin(user_id, hid): raise HTTPException(status_code=403, detail='admin only')
    row=update_command(command_id, payload.get('name',''), payload.get('aliases',''), payload.get('action','custom'), payload.get('description',''), bool(payload.get('enabled',True)))
    if not row: raise HTTPException(status_code=404, detail='command not found')
    return row

@app.delete('/api/commands/{command_id}')
def api_delete_command(command_id: int, user_id: str, household_id: int):
    if not is_household_admin(user_id, household_id): raise HTTPException(status_code=403, detail='admin only')
    return {'ok': delete_command(command_id)}

@app.get('/api/installments')
def api_installments(user_id: str, household_id: int):
    if not user_has_feature(user_id, household_id, 'installment'):
        raise HTTPException(status_code=403, detail='installment feature disabled')
    return {'plans': get_installments(household_id)}

@app.post('/api/installments')
async def api_add_installment(request: Request):
    payload=await request.json(); user_id=str(payload.get('user_id') or '').strip(); hid=int(payload.get('household_id') or 0)
    if not user_id or not hid or not is_household_admin(user_id,hid): raise HTTPException(status_code=403, detail='admin only')
    row=add_installment(user_id,hid,payload)
    if row is None: raise HTTPException(status_code=400, detail='save failed')
    return {'plans':row}

@app.post('/api/installments/payment')
async def api_add_installment_payment(request: Request):
    payload=await request.json(); user_id=str(payload.get('user_id') or '').strip(); hid=int(payload.get('household_id') or 0)
    if not user_id or not hid or not user_has_feature(user_id,hid,'installment'): raise HTTPException(status_code=403, detail='installment feature disabled')
    row=add_installment_payment(user_id,hid,payload)
    if row is None: raise HTTPException(status_code=400, detail='save failed')
    return {'plans':row}

@app.get('/api/loan')
def api_loan(user_id: str, household_id: int):
    if not user_has_feature(user_id, household_id, 'loan'):
        raise HTTPException(status_code=403, detail='loan feature disabled')
    m=get_mortgage(household_id)
    ins=get_house_insurance(household_id)
    exp=get_house_expenses(household_id)
    forecast=mortgage_forecast(m, int((m or {}).get('term_years') or 30)*12) if m else []
    # Overlay recorded real payments on the forecast so the UI reflects actual payments.
    if m and forecast and m.get('payments'):
        running=float(m.get('loan_amount') or 0)
        for i, p in enumerate(m.get('payments', [])):
            if i >= len(forecast): break
            principal=float(p.get('principal') or 0)
            extra=float(p.get('extra_principal') or 0)
            interest=float(p.get('interest') or 0)
            paid=float(p.get('amount') or 0)
            running=max(0.0, running-principal-extra)
            forecast[i] = {**forecast[i], 'date': p.get('payment_date') or forecast[i].get('date'), 'payment': paid, 'principal': principal, 'extra_principal': extra, 'interest': interest, 'balance': round(running,2), 'actual': True}
        # Recalculate future forecast from the actual current balance.
        last_actual=len(m.get('payments', []))
        if last_actual < len(forecast):
            future=mortgage_forecast({**m,'loan_amount':running,'start_date':forecast[last_actual-1].get('date') if last_actual else m.get('start_date')}, len(forecast)-last_actual)
            for j,row in enumerate(future):
                row['no']=last_actual+j+1
                forecast[last_actual+j]=row
    paid_principal=sum(float(x.get('principal') or 0) + float(x.get('extra_principal') or 0) for x in (m or {}).get('payments',[]))
    paid_interest=sum(float(x.get('interest') or 0) for x in (m or {}).get('payments',[]))
    actual_balance=max(0, float((m or {}).get('loan_amount') or 0)-paid_principal)
    insurance_forecasts={}
    for x in ins:
        if str(x.get('payment_method'))=='ผ่อนแยก':
            insurance_forecasts[str(x['id'])]=insurance_forecast(x,m,int(x.get('financed_installments') or 120))
    return {'mortgage':m,'forecast':forecast,'insurance':ins,'insurance_forecasts':insurance_forecasts,'expenses':exp,'paid_principal':round(paid_principal,2),'paid_interest':round(paid_interest,2),'actual_balance':round(actual_balance,2)}

@app.put('/api/loan')
async def api_save_loan(request: Request):
    payload=await request.json(); user_id=str(payload.get('user_id') or '').strip(); hid=int(payload.get('household_id') or 0)
    if not user_id or not hid or not is_household_admin(user_id,hid): raise HTTPException(status_code=403, detail='admin only')
    row=save_mortgage(user_id,hid,payload)
    if row is None: raise HTTPException(status_code=400, detail='save failed')
    return row

@app.post('/api/loan/payment')
async def api_loan_payment(request: Request):
    payload=await request.json(); user_id=str(payload.get('user_id') or '').strip(); hid=int(payload.get('household_id') or 0)
    if not user_id or not hid or not user_has_feature(user_id,hid,'loan'): raise HTTPException(status_code=403, detail='loan feature disabled')
    try:
        row=add_mortgage_payment(user_id,hid,payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if row is None: raise HTTPException(status_code=400, detail='no mortgage or invalid payment')
    return row

@app.put('/api/loan/payment')
async def api_update_loan_payment(request: Request):
    payload=await request.json(); user_id=str(payload.get('user_id') or '').strip(); hid=int(payload.get('household_id') or 0)
    try: row=update_mortgage_payment(user_id,hid,payload)
    except ValueError as e: raise HTTPException(status_code=400,detail=str(e))
    if row is None: raise HTTPException(status_code=400,detail='update failed')
    return row

@app.delete('/api/loan/payment/{payment_id}')
async def api_delete_loan_payment(payment_id:int, user_id:str, household_id:int):
    if not delete_mortgage_payment(user_id,household_id,payment_id): raise HTTPException(status_code=403,detail='delete failed')
    return {'ok':True}

@app.post('/api/loan/insurance')
async def api_loan_insurance(request: Request):
    payload=await request.json(); user_id=str(payload.get('user_id') or '').strip(); hid=int(payload.get('household_id') or 0)
    if not user_id or not hid or not is_household_admin(user_id,hid): raise HTTPException(status_code=403, detail='admin only')
    row=add_house_insurance(user_id,hid,payload)
    if row is None: raise HTTPException(status_code=400, detail='save failed')
    return row

@app.post('/api/loan/insurance/payment')
async def api_loan_insurance_payment(request: Request):
    payload=await request.json(); user_id=str(payload.get('user_id') or '').strip(); hid=int(payload.get('household_id') or 0)
    if not user_id or not hid or not user_has_feature(user_id,hid,'loan'): raise HTTPException(status_code=403, detail='loan feature disabled')
    row=add_house_insurance_payment(user_id,hid,payload)
    if row is None: raise HTTPException(status_code=400, detail='insurance is not a separate installment plan')
    return row

@app.put('/api/loan/insurance/payment')
async def api_update_insurance_payment(request: Request):
    payload=await request.json(); user_id=str(payload.get('user_id') or '').strip(); hid=int(payload.get('household_id') or 0)
    try: row=update_house_insurance_payment(user_id,hid,payload)
    except ValueError as e: raise HTTPException(status_code=400,detail=str(e))
    if row is None: raise HTTPException(status_code=400,detail='update failed')
    return row

@app.delete('/api/loan/insurance/payment/{payment_id}')
async def api_delete_insurance_payment(payment_id:int, user_id:str, household_id:int):
    if not delete_house_insurance_payment(user_id,household_id,payment_id): raise HTTPException(status_code=403,detail='delete failed')
    return {'ok':True}

@app.post('/api/loan/expense')
async def api_loan_expense(request: Request):
    payload=await request.json(); user_id=str(payload.get('user_id') or '').strip(); hid=int(payload.get('household_id') or 0)
    if not user_id or not hid or not user_has_feature(user_id,hid,'loan'): raise HTTPException(status_code=403, detail='loan feature disabled')
    row=add_house_expense(user_id,hid,payload)
    if row is None: raise HTTPException(status_code=400, detail='save failed')
    return row

@app.get('/api/features/me')
def api_my_features(user_id: str):
    user_id = str(user_id or '').strip()
    if not user_id:
        raise HTTPException(status_code=400, detail='user_id required')
    # Return only this user's effective system-level feature flags.
    # Super Admin always has access; other users get only features explicitly granted by Super Admin.
    from database import FEATURES, global_user_has_feature
    return {'features': {key: bool(global_user_has_feature(user_id, key)) for key in FEATURES}}

@app.get('/api/superadmin/status')
def api_superadmin_status(user_id: str):
    return {'is_super_admin': is_super_admin(user_id), 'user_id': user_id}

@app.get('/api/superadmin/features')
def api_superadmin_features(user_id: str):
    if not is_super_admin(user_id):
        raise HTTPException(status_code=403, detail='super admin only')
    return get_global_feature_permissions(user_id)

@app.put('/api/superadmin/features')
async def api_superadmin_set_feature(request: Request):
    data = await request.json()
    requester = str(data.get('user_id') or '').strip()
    target = str(data.get('target_user_id') or '').strip()
    feature = str(data.get('feature') or '').strip()
    enabled = bool(data.get('enabled'))
    if not is_super_admin(requester):
        raise HTTPException(status_code=403, detail='super admin only')
    if not set_global_feature(requester, target, feature, enabled):
        raise HTTPException(status_code=400, detail='invalid user or feature')
    return get_global_feature_permissions(requester)

@app.get('/api/permissions')
def api_permissions(user_id: str, household_id: int):
    data = get_member_permissions(user_id, household_id)
    if data is None: raise HTTPException(status_code=403, detail='not a household member')
    return data

@app.put('/api/permissions/member/{member_user_id}')
async def api_set_member_permissions(member_user_id: str, request: Request):
    payload = await request.json()
    requester = str(payload.get('user_id') or '').strip(); hid = int(payload.get('household_id') or 0)
    if not requester or not hid or not is_household_admin(requester, hid): raise HTTPException(status_code=403, detail='admin only')
    features = payload.get('features') or {}
    role = payload.get('role')
    if role is not None and not set_member_role(requester, hid, member_user_id, role):
        raise HTTPException(status_code=400, detail='cannot change this member role')
    if not set_member_features(requester, hid, member_user_id, features):
        raise HTTPException(status_code=400, detail='member not found')
    return get_member_permissions(requester, hid)

@app.post('/webhook')
async def webhook(request: Request):
    body = await request.body()
    if not verify_signature(body, request.headers.get('x-line-signature', '')):
        raise HTTPException(status_code=400, detail='invalid signature')
    payload = json.loads(body or '{}')
    for event in payload.get('events', []):
        try: await handle_event(event)
        except Exception as e: print('event error:', repr(e))
    return JSONResponse({'ok': True})

async def handle_event(event):
    if event.get('type') != 'message' or not event.get('replyToken'): return
    user_id = event.get('source', {}).get('userId', 'unknown')
    upsert_user(user_id)
    msg = event.get('message', {})
    if msg.get('type') == 'text':
        text = msg.get('text', '').strip()
        if text in ('รหัสของฉัน','my id','userid'):
            reply(event['replyToken'], [{'type':'text','text':f'🪪 LINE User ID ของคุณ\n\n{user_id}\n\nใช้รหัสนี้เชื่อม Dashboard MeeTang ได้ครับ'}]); return
        if text in ('บ้านของฉัน','จัดการบ้าน','บัญชีของฉัน','บัญชี','household'):
            hs=get_user_households(user_id); active=get_active_household(user_id)
            if not hs:
                reply(event['replyToken'], [{'type':'text','text':'🏠 ยังไม่มีบ้าน\n\nพิมพ์ “สร้างบ้าน บ้านของเรา” หรือกดปุ่มสร้างบ้านจากเมนูได้เลยครับ'}]); return
            reply(event['replyToken'], [household_flex(hs, active)]); return
        if text.lower() in ('help','ช่วย','เมนู','menu','วิธีใช้'):
            reply(event['replyToken'], [{'type':'text','text':help_message()}]); return
        cmd, arg = find_command(text)
        if cmd and cmd['action'] == 'help':
            reply(event['replyToken'], [{'type':'text','text':help_message()}]); return
        if cmd and cmd['action'] == 'summary' and not arg:
            h,hid=active_scope(user_id); reply(event['replyToken'], [summary_flex(get_summary(user_id=user_id, household_id=hid), h)]); return
        if cmd and cmd['action'] == 'recent' and not arg:
            h,hid=active_scope(user_id); reply(event['replyToken'], [recent_flex(get_recent(10,user_id=user_id,household_id=hid), h)]); return
        if cmd and cmd['action'] in ('income','expense') and arg:
            h,hid=active_scope(user_id)
            parsed=parse_text(arg,datetime.now(TZ).date().isoformat())
            if not parsed.get('amount'):
                reply(event['replyToken'], [{'type':'text','text':f'ลองพิมพ์ เช่น “{cmd["name"]} 5000” ครับ'}]); return
            parsed['type']=cmd['action']
            if cmd['action']=='income': parsed['category']='เงินออม/ลงทุน' if cmd['name']=='ฝากเงิน' else (parsed.get('category') or 'อื่นๆ')
            if cmd['action']=='expense': parsed['category']='เงินออม/ลงทุน' if cmd['name']=='ถอนเงิน' else (parsed.get('category') or 'อื่นๆ')
            tx=add_transaction(user_id=user_id, household_id=hid, source='command', original_text=text, payer_user_id=user_id, **parsed)
            payer_name=next((m.get('display_name') for m in (h or {}).get('members',[]) if m['user_id']==user_id), None)
            reply(event['replyToken'], [transaction_flex(tx,h,payer_name)]); return
        if cmd and cmd['action'] == 'delete_latest' and not arg:
            h,hid=active_scope(user_id); rows=get_recent(1,user_id=user_id,household_id=hid)
            ok=bool(rows and delete_transaction(rows[0]['id'],user_id=user_id,household_id=hid))
            reply(event['replyToken'], [{'type':'text','text':'ลบรายการล่าสุดเรียบร้อย 🗑️' if ok else 'ยังไม่มีรายการให้ลบครับ'}]); return
        if text in ('เพิ่มรายการ','add'):
            reply(event['replyToken'], [{'type':'text','text':'💰 เพิ่มรายการ\n\nพิมพ์ได้เลย เช่น\n• กินข้าว 120\n• เติมน้ำมัน 500\n• เงินเดือนเข้า 30000\n\nMeeTang จะบันทึกเข้าบ้านที่กำลังใช้งานอยู่ครับ 🐰'}]); return
        if text in ('สแกนสลิป','scan'):
            reply(event['replyToken'], [{'type':'text','text':'📸 ส่งรูปสลิปเข้ามาได้เลย เดี๋ยวผมอ่านยอด ร้าน และวันที่ให้'}]); return
        if text in ('สร้างบ้าน','สร้างบัญชีร่วม','สร้าง household'):
            reply(event['replyToken'], [{'type':'text','text':'🏠 สร้างบ้านใหม่\n\nพิมพ์ชื่อบ้านต่อท้ายได้เลย เช่น\n• สร้างบ้าน ร้านขนม\n• สร้างบ้าน บ้านแม่\n• สร้างบ้าน เที่ยวญี่ปุ่น\n\nใช้รูปแบบ “สร้างบ้าน ชื่อบ้าน” ครับ'}]); return
        if text.startswith('สร้างบ้าน '):
            name=text.split(None,1)[1].strip()
            if not name:
                reply(event['replyToken'], [{'type':'text','text':'กรุณาใส่ชื่อบ้าน เช่น “สร้างบ้าน ร้านขนม”'}]); return
            h = create_household(user_id, name)
            reply(event['replyToken'], [{'type':'text','text':f'🏠 สร้างบ้านใหม่แล้ว\nชื่อ: {h["name"]}\n\n⭐ ตอนนี้กำลังใช้งานบ้านนี้อยู่\nรหัสเชิญ: {h["invite_code"]}\n\nส่งรหัสนี้ให้คนที่ต้องการเข้าบัญชีร่วมได้เลย'}]); return
        if text.startswith('เข้าร่วม '):
            code=text.split(None,1)[1].strip()
            h=join_household(user_id,code)
            reply(event['replyToken'], [{'type':'text','text':f'เข้าร่วม {h["name"]} แล้ว 🏠' if h else 'ไม่พบรหัสเชิญนี้ ลองตรวจสอบอีกครั้ง'}]); return
        if text.startswith('ตั้งชื่อ '):
            name=text.split(None,1)[1].strip()
            if name:
                set_display_name(user_id, name)
                reply(event['replyToken'], [{'type':'text','text':f'ตั้งชื่อเป็น “{name}” แล้ว 👤'}]); return
        if text in ('สมาชิก','สมาชิกในบ้าน','สมาชิกบัญชี'):
            h=get_active_household(user_id)
            if not h:
                reply(event['replyToken'], [{'type':'text','text':'ยังไม่ได้เลือกบัญชีร่วมครับ'}]); return
            lines=['👥 สมาชิกในบัญชีร่วม']
            for i,m in enumerate(h['members'],1):
                name=m['display_name'] or f'สมาชิก {m["user_id"][-4:]}'
                lines.append(f'{i}. {name}' + (' 👑' if m['role']=='owner' else ''))
            reply(event['replyToken'], [{'type':'text','text':'\n'.join(lines)}]); return
        if text.startswith('ใช้บัญชี '):
            target=text.split(None,1)[1].strip()
            ok=False
            if target.isdigit():
                ok=set_active_household(user_id,int(target))
            else:
                hs=get_user_households(user_id)
                match=next((x for x in hs if x['name'].strip().lower()==target.lower()), None)
                ok=set_active_household(user_id,match['id']) if match else False
            active=get_active_household(user_id)
            reply(event['replyToken'], [{'type':'text','text':f'สลับไป “{active["name"]}” แล้ว ✅' if ok and active else 'ไม่พบบัญชีนี้ ลอง “บัญชีของฉัน” เพื่อดูชื่อบัญชี'}]); return
        if text.startswith('เปลี่ยนชื่อบ้าน '):
            h=get_active_household(user_id)
            name=text.split(None,2)[2].strip()
            ok=bool(h and rename_household(user_id,h['id'],name))
            reply(event['replyToken'], [{'type':'text','text':f'เปลี่ยนชื่อบ้านเป็น “{name}” แล้ว ✅' if ok else 'เปลี่ยนชื่อไม่ได้ (ต้องเป็นเจ้าของบ้าน)'}]); return
        if text in ('ลบบ้าน','ลบบัญชีร่วม'):
            h=get_active_household(user_id)
            if not h:
                reply(event['replyToken'], [{'type':'text','text':'ตอนนี้ยังไม่มีบ้านที่กำลังใช้งานอยู่ครับ'}]); return
            if h['owner_user_id'] != user_id:
                reply(event['replyToken'], [{'type':'text','text':'บ้านนี้คุณไม่ได้เป็นเจ้าของ จึงลบไม่ได้ครับ\nถ้าต้องการออก ให้พิมพ์ “ออกจากบ้าน”'}]); return
            reply(event['replyToken'], [{'type':'text','text':f'⚠️ ยืนยันการลบบ้าน “{h["name"]}” ?\n\nรายการและข้อมูลการหารเงินของบ้านนี้จะถูกลบทั้งหมด\n\nถ้ายืนยัน พิมพ์ “ยืนยันลบบ้าน”'}]); return
        if text == 'ยืนยันลบบ้าน':
            h=get_active_household(user_id)
            if not h:
                reply(event['replyToken'], [{'type':'text','text':'ไม่พบบ้านที่กำลังใช้งานอยู่ครับ'}]); return
            if h['owner_user_id'] != user_id:
                reply(event['replyToken'], [{'type':'text','text':'เฉพาะเจ้าของบ้านเท่านั้นที่ลบบ้านได้ครับ'}]); return
            deleted=delete_household(user_id,h['id'])
            reply(event['replyToken'], [{'type':'text','text':f'ลบบ้าน “{deleted["name"]}” เรียบร้อยแล้ว 🗑️' if deleted else 'ลบบ้านไม่สำเร็จ'}]); return
        if text == 'ออกจากบ้าน':
            h=get_active_household(user_id)
            ok=bool(h and leave_household(user_id,h['id']))
            reply(event['replyToken'], [{'type':'text','text':f'ออกจาก “{h["name"]}” แล้ว 🚪' if ok else 'ออกจากบ้านไม่ได้ ถ้าคุณเป็นเจ้าของบ้านให้ใช้ “ลบบ้าน” แทน'}]); return
        h,hid=active_scope(user_id)
        if any(k in text for k in ('สรุปค่าใช้จ่ายร่วม','ยอดร่วม','ใครจ่าย','เคลียร์ยอด','settlement')):
            if not h:
                reply(event['replyToken'], [{'type':'text','text':'ฟังก์ชันนี้ใช้กับบัญชีร่วมครับ 🏠\nพิมพ์ “สร้างบ้าน” หรือ “เข้าร่วม รหัส” ก่อน'}]); return
            reply(event['replyToken'], [settlement_flex(get_settlement(hid))]); return
        if any(k in text for k in ('สรุป','summary','เดือนนี้')):
            reply(event['replyToken'], [summary_flex(get_summary(user_id=user_id, household_id=hid), h)]); return
        if any(k in text for k in ('รายการล่าสุด','รายการ','recent')):
            reply(event['replyToken'], [recent_flex(get_recent(10,user_id=user_id,household_id=hid), h)]); return
        if text.startswith('ลบ '):
            try: tx_id=int(text.split()[1]); ok=delete_transaction(tx_id,user_id=user_id,household_id=hid)
            except: ok=False
            reply(event['replyToken'], [{'type':'text','text':'ลบรายการเรียบร้อย 🗑️' if ok else 'ไม่พบรายการนี้ หรือไม่มีสิทธิ์ลบ'}]); return
        parsed=parse_text(text,datetime.now(TZ).date().isoformat())
        if not parsed.get('amount'):
            reply(event['replyToken'], [{'type':'text','text':'ยังอ่านจำนวนเงินไม่ได้ 😅\nลอง “กินข้าว 120” หรือส่งรูปสลิป'}]); return
        split_mode='self'; participants=[user_id]; split_amounts=None
        split=parse_split_instruction(text,h,user_id) if h else None
        if split:
            split_mode, participants, split_amounts, _ = split
        tx=add_transaction(user_id=user_id, household_id=hid, source='text', original_text=text, payer_user_id=user_id,
                           split_mode=split_mode, split_participants=participants, split_amounts=split_amounts, **parsed)
        payer_name=next((m.get('display_name') for m in (h or {}).get('members',[]) if m['user_id']==user_id), None)
        reply(event['replyToken'], [transaction_flex(tx,h,payer_name)]); return

    if msg.get('type') == 'image':
        reply(event['replyToken'], [{'type':'text','text':'📸 รับรูปแล้วครับ (โหมดฟรี)\nตอนนี้ยังไม่ได้ใช้ AI อ่านสลิปอัตโนมัติ เพื่อไม่ให้มีค่า API\n\nพิมพ์ยอดตามหลังรูป เช่น “350 ร้าน ABC” แล้วผมจะบันทึกให้ครับ 💰'}]); return
        split_mode='self'; participants=[user_id]; split_amounts=None
        split=parse_split_instruction(parsed.get('note',''),h,user_id) if h else None
        if split:
            split_mode, participants, split_amounts, _ = split
        tx=add_transaction(user_id=user_id, household_id=hid, source='slip', original_text='LINE image', payer_user_id=user_id,
                           split_mode=split_mode, split_participants=participants, split_amounts=split_amounts, **parsed)
        payer_name=next((m.get('display_name') for m in (h or {}).get('members',[]) if m['user_id']==user_id), None)
        reply(event['replyToken'], [transaction_flex(tx,h,payer_name)]); return

    reply(event['replyToken'], [{'type':'text','text':'ตอนนี้รองรับข้อความและรูปสลิปครับ 💰'}])
