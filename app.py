import os, json, base64, hashlib, hmac
from datetime import datetime
from zoneinfo import ZoneInfo
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse, JSONResponse
import requests

from database import (init_db, upsert_user, create_household, join_household, get_active_household,
                      get_user_households, set_active_household, add_transaction, get_summary, get_recent,
                      get_categories, delete_transaction, set_display_name, get_household, get_settlement,
                      rename_household, delete_household, leave_household)
from ai import parse_text, parse_slip
from split_utils import parse_split_instruction
from flex import summary_flex, transaction_flex, recent_flex, settlement_flex, help_text

TZ = ZoneInfo(os.getenv('TZ', 'Asia/Bangkok'))
LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET', '')
LINE_ACCESS_TOKEN = os.getenv('LINE_ACCESS_TOKEN', '') or os.getenv('LINE_CHANNEL_ACCESS_TOKEN', '')
app = FastAPI(title='MeeTang LINE Bot')
init_db()


def setup_rich_menu_on_startup():
    """Create and activate MeeTang's Rich Menu automatically on deploy/startup."""
    if not LINE_ACCESS_TOKEN:
        print('Rich Menu: skipped (LINE access token is missing)')
        return
    image_path = os.path.join(os.path.dirname(__file__), 'rich_menu.png')
    if not os.path.exists(image_path):
        print('Rich Menu: skipped (rich_menu.png is missing)')
        return
    headers = {'Authorization': f'Bearer {LINE_ACCESS_TOKEN}'}
    try:
        # Reuse an existing MeeTang menu if it already exists; otherwise create it.
        existing = requests.get('https://api.line.me/v2/bot/richmenu/list', headers=headers, timeout=20)
        existing.raise_for_status()
        menus = existing.json().get('richmenus', [])
        menu = next((m for m in menus if m.get('name') == 'MeeTang Main Menu'), None)

        if menu:
            menu_id = menu['richMenuId']
            print('Rich Menu: using existing', menu_id)
        else:
            menu_data = {
                'size': {'width': 2500, 'height': 1686},
                'selected': True,
                'name': 'MeeTang Main Menu',
                'chatBarText': '💰 MeeTang',
                'areas': [
                    {'bounds': {'x': 0, 'y': 0, 'width': 833, 'height': 843}, 'action': {'type': 'message', 'text': 'เพิ่มรายการ'}},
                    {'bounds': {'x': 833, 'y': 0, 'width': 834, 'height': 843}, 'action': {'type': 'message', 'text': 'สรุปเดือนนี้'}},
                    {'bounds': {'x': 1667, 'y': 0, 'width': 833, 'height': 843}, 'action': {'type': 'message', 'text': 'รายการล่าสุด'}},
                    {'bounds': {'x': 0, 'y': 843, 'width': 833, 'height': 843}, 'action': {'type': 'message', 'text': 'บ้านของฉัน'}},
                    {'bounds': {'x': 833, 'y': 843, 'width': 834, 'height': 843}, 'action': {'type': 'message', 'text': 'เคลียร์ยอด'}},
                    {'bounds': {'x': 1667, 'y': 843, 'width': 833, 'height': 843}, 'action': {'type': 'message', 'text': 'ช่วย'}},
                ]
            }
            r = requests.post('https://api.line.me/v2/bot/richmenu', headers={**headers, 'Content-Type': 'application/json'}, json=menu_data, timeout=20)
            r.raise_for_status()
            menu_id = r.json()['richMenuId']
            print('Rich Menu: created', menu_id)

        with open(image_path, 'rb') as f:
            r = requests.post(
                f'https://api-data.line.me/v2/bot/richmenu/{menu_id}/content',
                headers={**headers, 'Content-Type': 'image/png'},
                data=f, timeout=60
            )
            r.raise_for_status()

        r = requests.post(f'https://api.line.me/v2/bot/user/all/richmenu/{menu_id}', headers=headers, timeout=20)
        r.raise_for_status()
        print('Rich Menu: activated successfully')
    except Exception as e:
        # Never prevent the bot from starting if LINE's Rich Menu API has a temporary issue.
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
                reply(event['replyToken'], [{'type':'text','text':'🏠 ยังไม่มีบ้าน\n\nกด “สร้างบ้าน” หรือพิมพ์\nสร้างบ้าน บ้านของเรา'}]); return
            lines=['🏠 บ้านของฉัน','']
            for i,h in enumerate(hs,1):
                mark='⭐ กำลังใช้งาน' if active and h['id']==active['id'] else ''
                lines.append(f'{i}. {h["name"]} {mark}'.strip())
            lines += ['', 'เลือกบ้าน: ใช้บัญชี <ชื่อบ้าน>', 'สร้างใหม่: สร้างบ้าน <ชื่อบ้าน>', 'จัดการ: เปลี่ยนชื่อบ้าน <ชื่อใหม่>', 'ลบ: ลบบ้าน']
            reply(event['replyToken'], [{'type':'text','text':'\n'.join(lines)}]); return
        if text.lower() in ('help','ช่วย','เมนู','menu','วิธีใช้'):
            reply(event['replyToken'], [{'type':'text','text':help_message()}]); return
        if text in ('เพิ่มรายการ','add'):
            reply(event['replyToken'], [{'type':'text','text':'พิมพ์ได้เลย เช่น\n• กินข้าว 120\n• เติมน้ำมัน 500\n• เงินเดือนเข้า 30000'}]); return
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
        h,hid=active_scope(user_id)
        reply(event['replyToken'], [{'type':'text','text':'📸 รับรูปแล้วครับ (โหมดฟรี)\nตอนนี้ยังไม่ได้ใช้ AI อ่านสลิปอัตโนมัติ เพื่อไม่ให้มีค่า API\n\nพิมพ์ยอด เช่น “สลิป 350 ร้าน ABC” แล้วผมจะบันทึกให้ครับ 💰'}])
        parsed=parse_slip(get_line_content(msg['id']))
        reply(event['replyToken'], [{'type':'text','text':'โหมดฟรียังไม่อ่านยอดจากรูปอัตโนมัติครับ 😅\nพิมพ์ยอดตามหลังรูป เช่น “350 ร้าน ABC” แล้วผมจะบันทึกให้'}]); return
        split_mode='self'; participants=[user_id]; split_amounts=None
        split=parse_split_instruction(parsed.get('note',''),h,user_id) if h else None
        if split:
            split_mode, participants, split_amounts, _ = split
        tx=add_transaction(user_id=user_id, household_id=hid, source='slip', original_text='LINE image', payer_user_id=user_id,
                           split_mode=split_mode, split_participants=participants, split_amounts=split_amounts, **parsed)
        payer_name=next((m.get('display_name') for m in (h or {}).get('members',[]) if m['user_id']==user_id), None)
        reply(event['replyToken'], [transaction_flex(tx,h,payer_name)]); return

    reply(event['replyToken'], [{'type':'text','text':'ตอนนี้รองรับข้อความและรูปสลิปครับ 💰'}])
