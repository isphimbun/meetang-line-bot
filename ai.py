import os, json, base64, re, requests

OPENAI_API_KEY=os.getenv('OPENAI_API_KEY','')
MODEL=os.getenv('OPENAI_MODEL','gpt-5-mini')
CATS=['อาหาร','บ้าน','เดินทาง','ช้อปปิ้ง','บิล/ค่าสาธารณูปโภค','สุขภาพ','บันเทิง','ท่องเที่ยว','เงินออม/ลงทุน','เงินเดือน','ธุรกิจ','อื่นๆ']

SCHEMA={
  'type':'object','properties':{
    'type':{'type':'string','enum':['income','expense']},
    'amount':{'type':['number','null']},
    'category':{'type':'string','enum':CATS},
    'merchant':{'type':'string'},
    'note':{'type':'string'},
    'occurred_at':{'type':'string'}
  },'required':['type','amount','category','merchant','note','occurred_at'],'additionalProperties':False
}

def call_ai(content):
    if not OPENAI_API_KEY: return None
    body={'model':MODEL,'input':[{'role':'user','content':content}],
          'text':{'format':{'type':'json_schema','name':'transaction','strict':True,'schema':SCHEMA}},
          'store':False}
    r=requests.post('https://api.openai.com/v1/responses',headers={'Authorization':f'Bearer {OPENAI_API_KEY}','Content-Type':'application/json'},json=body,timeout=45)
    r.raise_for_status(); data=r.json()
    out=data.get('output_text','').strip()
    return json.loads(out)

def fallback(text, today):
    nums=re.findall(r'(?<!\d)(\d+(?:[.,]\d{1,2})?)(?!\d)',text.replace(',',''))
    amount=float(nums[-1]) if nums else None
    lower=text.lower()
    cat='อื่นๆ'
    if any(x in text for x in ['กิน','ข้าว','กาแฟ','อาหาร','ชาบู','ร้านอาหาร','7-11','เซเว่น']): cat='อาหาร'
    elif any(x in text for x in ['น้ำมัน','แท็กซี่','รถ','bts','mrt','เดินทาง']): cat='เดินทาง'
    elif any(x in text for x in ['บ้าน','ค่าไฟ','ค่าน้ำ','ค่าเน็ต','ค่าโทรศัพท์']): cat='บ้าน' if 'บ้าน' in text else 'บิล/ค่าสาธารณูปโภค'
    elif any(x in text for x in ['เงินเดือน','เงินเข้า','รายรับ','ได้รับ']): cat='เงินเดือน'; return {'type':'income','amount':amount,'category':cat,'merchant':'','note':text,'occurred_at':today}
    elif any(x in text for x in ['ซื้อ','ช้อป','เสื้อ','ของ']): cat='ช้อปปิ้ง'
    return {'type':'expense','amount':amount,'category':cat,'merchant':'','note':text,'occurred_at':today}

def parse_text(text,today):
    prompt=f'''Parse this Thai personal finance message into one transaction. Today is {today}. Infer relative dates. Amount must be numeric THB. If it says salary/received/money in, type income; otherwise expense. Choose the best category from {CATS}. Return only the schema JSON. Message: {text}'''
    try: return call_ai(prompt) or fallback(text,today)
    except Exception as e:
        print('AI text fallback:',e); return fallback(text,today)

def parse_slip(image_bytes):
    b64=base64.b64encode(image_bytes).decode()
    prompt='''Read this Thai bank/payment slip and extract a single personal finance transaction. Use the transfer/payment amount, merchant or recipient if visible, and date/time if visible. Usually a payment slip means expense unless it clearly shows money received. Category should be one of the allowed categories. If uncertain amount, return null. Return only JSON schema.'''
    content=[{'type':'input_text','text':prompt},{'type':'input_image','image_url':f'data:image/jpeg;base64,{b64}'}]
    try: return call_ai(content) or {'amount':None}
    except Exception as e: print('AI slip error:',e); return {'amount':None}
