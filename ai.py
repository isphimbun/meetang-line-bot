import re
from datetime import datetime

CATS=['อาหาร','บ้าน','เดินทาง','ช้อปปิ้ง','บิล/ค่าสาธารณูปโภค','สุขภาพ','บันเทิง','ท่องเที่ยว','เงินออม/ลงทุน','เงินเดือน','ธุรกิจ','อื่นๆ']

KEYWORDS={
    'อาหาร':['ข้าว','กิน','อาหาร','กาแฟ','กาแฟ','ชา','ชาบู','หมูกระทะ','ร้านอาหาร','ของกิน','ขนม','น้ำ','เครื่องดื่ม','7-11','เซเว่น'],
    'บ้าน':['ค่าเช่า','คอนโด','บ้าน','เฟอร์นิเจอร์','ของใช้บ้าน','ของเข้าบ้าน'],
    'เดินทาง':['น้ำมัน','เติมน้ำมัน','แท็กซี่','grab','bolt','รถไฟ','mrt','bts','ทางด่วน','ที่จอดรถ','เดินทาง'],
    'ช้อปปิ้ง':['ซื้อ','ช้อป','เสื้อ','รองเท้า','กระเป๋า','เครื่องสำอาง','ของใช้'],
    'บิล/ค่าสาธารณูปโภค':['ค่าไฟ','ค่าน้ำ','ค่าเน็ต','อินเทอร์เน็ต','โทรศัพท์','ค่าโทร','บิล'],
    'สุขภาพ':['ยา','หมอ','โรงพยาบาล','คลินิก','สุขภาพ'],
    'บันเทิง':['หนัง','เกม','คอนเสิร์ต','เที่ยวเล่น','karaoke','คาราโอเกะ'],
    'ท่องเที่ยว':['โรงแรม','ที่พัก','เที่ยว','ตั๋วเครื่องบิน','เครื่องบิน'],
    'เงินออม/ลงทุน':['ออม','เก็บเงิน','ลงทุน','กองทุน','หุ้น'],
    'ธุรกิจ':['วัตถุดิบ','แพ็กเกจ','ค่าส่ง','ธุรกิจ','ร้านค้า'],
}

def amount_from_text(text):
    # Prefer a number that looks like a baht amount, including commas/decimals.
    nums=re.findall(r'(?<!\d)(\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)(?!\d)', text)
    if not nums: return None
    vals=[float(x.replace(',','')) for x in nums]
    # Ignore obvious dates/years when another plausible amount exists.
    plausible=[v for v in vals if v < 10000000 and not (1900 <= v <= 2100)]
    return plausible[-1] if plausible else vals[-1]

def category_for(text, tx_type):
    low=text.lower()
    if tx_type=='income':
        if any(k in low for k in ['เงินเดือน','salary','ค่าจ้าง','รายได้','โบนัส']): return 'เงินเดือน'
        return 'อื่นๆ'
    for cat, kws in KEYWORDS.items():
        if any(k.lower() in low for k in kws): return cat
    return 'อื่นๆ'

def parse_text(text, today=None):
    low=text.lower().strip()
    income=bool(re.search(r'เงินเดือน|เงินเข้า|รายรับ|รายได้|รับเงิน|โบนัส|salary|income', low))
    tx_type='income' if income else 'expense'
    amount=amount_from_text(text)
    # Simple date support: today / yesterday. Full natural-language dates stay manual in Free edition.
    occurred_at=today or datetime.now().date().isoformat()
    if 'เมื่อวาน' in text:
        try:
            from datetime import date,timedelta
            occurred_at=(date.fromisoformat(occurred_at)-timedelta(days=1)).isoformat()
        except Exception: pass
    merchant=''
    note=text.strip()
    return {'type':tx_type,'amount':amount,'category':category_for(text,tx_type),'merchant':merchant,'note':note,'occurred_at':occurred_at}

def parse_slip(content: bytes):
    # Free edition intentionally does not call a paid vision API.
    # The bot asks the user to type the amount instead of pretending it read the image.
    return {'type':'expense','amount':None,'category':'อื่นๆ','merchant':'','note':'','occurred_at':datetime.now().date().isoformat()}
