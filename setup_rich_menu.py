import os, json, requests
from pathlib import Path

TOKEN = os.getenv('LINE_ACCESS_TOKEN','') or os.getenv('LINE_CHANNEL_ACCESS_TOKEN','')
IMAGE = Path(__file__).parent / 'rich_menu.jpg'
if not TOKEN: raise SystemExit('Missing LINE access token')
if not IMAGE.exists(): raise SystemExit(f'Missing {IMAGE}')
headers={'Authorization':f'Bearer {TOKEN}'}
menu={
  'size': {'width':2500,'height':1686},
  'selected': True,
  'name': 'MeeTang Main Menu v31 Dashboard',
  'chatBarText': '💰 มีตังค์',
  'areas': [
    {'bounds':{'x':0,'y':0,'width':833,'height':843},'action':{'type':'message','text':'เพิ่มรายการ'}},
    {'bounds':{'x':833,'y':0,'width':834,'height':843},'action':{'type':'message','text':'รายการล่าสุด'}},
    {'bounds':{'x':1667,'y':0,'width':833,'height':843},'action':{'type':'message','text':'สรุปเดือนนี้'}},
    {'bounds':{'x':0,'y':843,'width':833,'height':843},'action':{'type':'message','text':'บ้านของฉัน'}},
    {'bounds':{'x':833,'y':843,'width':834,'height':843},'action':{'type':'message','text':'เคลียร์ยอด'}},
    {'bounds':{'x':1667,'y':843,'width':833,'height':843},'action':{'type':'uri','uri':os.getenv('DASHBOARD_URL','https://meetang-bot.onrender.com')}},
  ]
}
r=requests.post('https://api.line.me/v2/bot/richmenu',headers={**headers,'Content-Type':'application/json'},json=menu,timeout=30);r.raise_for_status();menu_id=r.json()['richMenuId']
with IMAGE.open('rb') as f:
    ctype='image/jpeg' if IMAGE.suffix.lower() in ('.jpg','.jpeg') else 'image/jpeg'
    r=requests.post(f'https://api-data.line.me/v2/bot/richmenu/{menu_id}/content',headers={**headers,'Content-Type':ctype},data=f,timeout=60);r.raise_for_status()
r=requests.post(f'https://api.line.me/v2/bot/user/all/richmenu/{menu_id}',headers=headers,timeout=30);r.raise_for_status()
print('MeeTang Rich Menu ready:',json.dumps({'richMenuId':menu_id},ensure_ascii=False))
