import os, json, requests
from pathlib import Path

TOKEN = os.getenv('LINE_ACCESS_TOKEN','')
PUBLIC_URL = os.getenv('PUBLIC_URL','').rstrip('/')
IMAGE = Path(__file__).parent / 'rich_menu.png'

if not TOKEN:
    raise SystemExit('Missing LINE_ACCESS_TOKEN')
if not IMAGE.exists():
    raise SystemExit(f'Missing {IMAGE}')

headers={'Authorization':f'Bearer {TOKEN}'}
menu={
  'size': {'width':2500,'height':1686},
  'selected': True,
  'name': 'MoneyMate Main Menu',
  'chatBarText': '💰 MoneyMate',
  'areas': [
    {'bounds':{'x':0,'y':0,'width':833,'height':843},'action':{'type':'message','text':'เพิ่มรายการ'}},
    {'bounds':{'x':833,'y':0,'width':834,'height':843},'action':{'type':'message','text':'สแกนสลิป'}},
    {'bounds':{'x':1667,'y':0,'width':833,'height':843},'action':{'type':'message','text':'สรุปเดือนนี้'}},
    {'bounds':{'x':0,'y':843,'width':833,'height':843},'action':{'type':'message','text':'รายการล่าสุด'}},
    {'bounds':{'x':833,'y':843,'width':834,'height':843},'action':{'type':'message','text':'ช่วย'}},
    {'bounds':{'x':1667,'y':843,'width':833,'height':843},'action':{'type':'uri','uri': PUBLIC_URL or 'https://example.com'}},
  ]
}
r=requests.post('https://api.line.me/v2/bot/richmenu',headers={**headers,'Content-Type':'application/json'},json=menu,timeout=30)
r.raise_for_status()
menu_id=r.json()['richMenuId']
print('Created:',menu_id)

with IMAGE.open('rb') as f:
    r=requests.post(f'https://api-data.line.me/v2/bot/richmenu/{menu_id}/content',headers={**headers,'Content-Type':'image/png'},data=f,timeout=60)
r.raise_for_status()
print('Uploaded image')

r=requests.post(f'https://api.line.me/v2/bot/user/all/richmenu/{menu_id}',headers=headers,timeout=30)
r.raise_for_status()
print('Set as default rich menu')
print(json.dumps({'richMenuId':menu_id},ensure_ascii=False))
