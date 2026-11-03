"""ล็อกอิน Dashboard ด้วยลิงก์จาก LINE (ไม่ต้องพิมพ์ LINE User ID ในเว็บอีกต่อไป)

ขั้นตอน: พิมพ์ "เปิดแดชบอร์ด" ใน LINE → บอทส่งลิงก์ที่มี token อายุ 10 นาที →
เว็บแลก token เป็น session token (30 วัน) เก็บในเบราว์เซอร์ → ทุก /api/* ต้องแนบ Authorization: Bearer <session>
เซิร์ฟเวอร์ "บังคับ" user_id จาก token (ทับค่า user_id ที่ client ส่งมาทั้ง query และ JSON body)
จึงปลอมเป็นคนอื่นไม่ได้แม้จะรู้ LINE User ID

ตั้ง DASH_SECRET (สตริงสุ่มยาวๆ) ใน Environment ถ้าไม่ตั้งจะใช้ LINE_CHANNEL_SECRET แทน
ปิดระบบนี้ชั่วคราว (ไม่แนะนำ): DASH_AUTH=0
"""
import os, json, hmac, hashlib, base64, time
from urllib.parse import parse_qsl, urlencode

LOGIN_TTL = 10 * 60
SESSION_TTL = 30 * 24 * 3600
PUBLIC_API = ('/api/auth/exchange', '/api/backup/status')


def _secret():
    return (os.getenv('DASH_SECRET') or os.getenv('LINE_CHANNEL_SECRET') or '').encode()


def auth_enabled():
    if os.getenv('DASH_AUTH', '1').strip().lower() in ('0', 'false', 'no', 'off'): return False
    return bool(_secret())


def _b64(b): return base64.urlsafe_b64encode(b).decode().rstrip('=')
def _unb64(s): return base64.urlsafe_b64decode(s + '=' * (-len(s) % 4))


def make_token(user_id, kind='session', ttl=None):
    ttl = ttl or (LOGIN_TTL if kind == 'login' else SESSION_TTL)
    body = _b64(json.dumps({'u': user_id, 'k': kind, 'e': int(time.time()) + ttl}, separators=(',', ':')).encode())
    sig = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
    return f'{body}.{sig}'


def verify_token(token, kind='session'):
    """คืน user_id ถ้า token ถูกต้อง/ยังไม่หมดอายุ/ชนิดตรง ไม่งั้นคืน None"""
    try:
        body, sig = str(token or '').split('.', 1)
        good = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, good): return None
        d = json.loads(_unb64(body))
        if d.get('k') != kind or int(d.get('e', 0)) < time.time() or not d.get('u'): return None
        return str(d['u'])
    except Exception:
        return None


async def _deny(send, status=401, detail='unauthorized'):
    body = json.dumps({'detail': detail}).encode()
    await send({'type': 'http.response.start', 'status': status,
                'headers': [(b'content-type', b'application/json'), (b'content-length', str(len(body)).encode())]})
    await send({'type': 'http.response.body', 'body': body})


class AuthMiddleware:
    """ASGI middleware: ตรวจ session token ของทุก /api/* แล้วบังคับ user_id ให้เป็นของเจ้าของ token"""
    def __init__(self, app): self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get('path', '')
        if scope['type'] != 'http' or not path.startswith('/api/') or path in PUBLIC_API or not auth_enabled():
            return await self.app(scope, receive, send)
        headers = dict(scope.get('headers') or [])
        auth = headers.get(b'authorization', b'').decode()
        uid = verify_token(auth[7:] if auth.lower().startswith('bearer ') else '', 'session')
        if not uid:
            return await _deny(send)
        scope = dict(scope)
        qs = [(k, v) for k, v in parse_qsl(scope.get('query_string', b'').decode(), keep_blank_values=True) if k != 'user_id']
        scope['query_string'] = urlencode(qs + [('user_id', uid)]).encode()
        ctype = headers.get(b'content-type', b'').decode().lower()
        if scope.get('method') in ('POST', 'PUT', 'PATCH', 'DELETE') and 'json' in ctype:
            body = b''
            while True:
                msg = await receive()
                if msg['type'] == 'http.request':
                    body += msg.get('body', b'')
                    if not msg.get('more_body'): break
                else: break
            try:
                data = json.loads(body) if body else None
                if isinstance(data, dict):
                    data['user_id'] = uid
                    body = json.dumps(data, ensure_ascii=False).encode()
            except ValueError:
                pass
            scope['headers'] = [(k, v) for k, v in scope['headers'] if k != b'content-length'] + [(b'content-length', str(len(body)).encode())]
            sent = False
            async def new_receive():
                nonlocal sent
                if not sent:
                    sent = True
                    return {'type': 'http.request', 'body': body, 'more_body': False}
                return await receive()
            return await self.app(scope, new_receive, send)
        return await self.app(scope, receive, send)
