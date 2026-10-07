import os, json, base64, hashlib, hmac
from datetime import datetime
from zoneinfo import ZoneInfo
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse, JSONResponse
import requests

from database import (init_db, upsert_user, create_household, join_household, get_active_household,
                      get_user_households, set_active_household, add_transaction, get_summary, get_recent,
                      get_categories, delete_transaction, set_display_name, get_household, get_settlement)
from ai import parse_text, parse_slip
from split_utils import parse_split_instruction
from flex import summary_flex, transaction_flex, recent_flex, settlement_flex, help_text

TZ = ZoneInfo(os.getenv('TZ', 'Asia/Bangkok'))
LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET', '')
LINE_ACCESS_TOKEN = os.getenv('LINE_ACCESS_TOKEN', '') or os.getenv('LINE_CHANNEL_ACCESS_TOKEN', '')
app = FastAPI(title='MoneyMate LINE Bot')
init_db()


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
        if text.lower() in ('help','ช่วย','เมนู','menu','วิธีใช้'):
            reply(event['replyToken'], [{'type':'text','text':help_message()}]); return
        if text in ('เพิ่มรายการ','add'):
            reply(event['replyToken'], [{'type':'text','text':'พิมพ์ได้เลย เช่น\n• กินข้าว 120\n• เติมน้ำมัน 500\n• เงินเดือนเข้า 30000'}]); return
        if text in ('สแกนสลิป','scan'):
            reply(event['replyToken'], [{'type':'text','text':'📸 ส่งรูปสลิปเข้ามาได้เลย เดี๋ยวผมอ่านยอด ร้าน และวันที่ให้'}]); return
        if text in ('สร้างบ้าน','สร้างบัญชีร่วม','สร้าง household'):
            h = create_household(user_id, 'บ้านของเรา')
            reply(event['replyToken'], [{'type':'text','text':f'🏠 สร้างบัญชีร่วมแล้ว\nชื่อ: {h["name"]}\n\nรหัสเชิญ: {h["invite_code"]}\n\nส่งรหัสนี้ให้คนที่ต้องการเข้าบัญชีร่วมได้เลย'}]); return
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
        if text in ('บัญชีของฉัน','บัญชี','household'):
            hs=get_user_households(user_id); active=get_active_household(user_id)
            if not hs:
                reply(event['replyToken'], [{'type':'text','text':'ตอนนี้ยังไม่มีบัญชีร่วม\nพิมพ์ “สร้างบ้าน” เพื่อสร้างบัญชีร่วม'}]); return
            lines=['🏠 บัญชีของคุณ']
            for h in hs: lines.append(f'• {h["name"]} — รหัส {h["invite_code"]}' + (' ⭐ ใช้งานอยู่' if active and h['id']==active['id'] else ''))
            reply(event['replyToken'], [{'type':'text','text':'\n'.join(lines)}]); return
        if text.startswith('ใช้บัญชี '):
            try: hid=int(text.split(None,1)[1]); ok=set_active_household(user_id,hid)
            except: ok=False
            reply(event['replyToken'], [{'type':'text','text':'สลับบัญชีเรียบร้อย ✅' if ok else 'สลับบัญชีไม่สำเร็จ'}]); return
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
        reply(event['replyToken'], [{'type':'text','text':'กำลังอ่านสลิปให้ครับ 📸'}])
        parsed=parse_slip(get_line_content(msg['id']))
        if not parsed.get('amount'):
            reply(event['replyToken'], [{'type':'text','text':'อ่านยอดจากสลิปไม่สำเร็จ 😅\nลองส่งรูปที่คมชัดขึ้น หรือพิมพ์ยอดเอง'}]); return
        split_mode='self'; participants=[user_id]; split_amounts=None
        split=parse_split_instruction(parsed.get('note',''),h,user_id) if h else None
        if split:
            split_mode, participants, split_amounts, _ = split
        tx=add_transaction(user_id=user_id, household_id=hid, source='slip', original_text='LINE image', payer_user_id=user_id,
                           split_mode=split_mode, split_participants=participants, split_amounts=split_amounts, **parsed)
        payer_name=next((m.get('display_name') for m in (h or {}).get('members',[]) if m['user_id']==user_id), None)
        reply(event['replyToken'], [transaction_flex(tx,h,payer_name)]); return

    reply(event['replyToken'], [{'type':'text','text':'ตอนนี้รองรับข้อความและรูปสลิปครับ 💰'}])
