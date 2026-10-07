import math


def _money(v):
    return f"฿{float(v or 0):,.0f}"


def _txt(text, size='sm', color='#3B3338', weight=None, wrap=False, margin=None, flex=None, align=None):
    d={'type':'text','text':str(text),'size':size,'color':color,'wrap':wrap}
    if weight: d['weight']=weight
    if margin: d['margin']=margin
    if flex is not None: d['flex']=flex
    if align: d['align']=align
    return d


def _pill(text, bg='#FFE3EC', color='#6B2737'):
    return {'type':'box','layout':'vertical','backgroundColor':bg,'cornerRadius':'12px','paddingAll':'7px','contents':[_txt(text,'xs',color,'bold',True)]}


def _metric(label, value, bg):
    return {'type':'box','layout':'vertical','backgroundColor':bg,'cornerRadius':'14px','paddingAll':'10px','flex':1,
            'contents':[_txt(label,'xs','#7A6D74'),_txt(value,'lg','#2B2428','bold',False,'sm')]}


def transaction_flex(tx, household=None, payer_name=None):
    is_income = tx.get('type') == 'income'
    category = tx.get('category') or 'อื่นๆ'
    merchant = tx.get('merchant') or tx.get('note') or '-'
    occurred = str(tx.get('occurred_at') or '')[:10]
    amount_color = '#16844A' if is_income else '#D94B6A'
    title = '💰 บันทึกรายรับแล้ว' if is_income else '✅ บันทึกรายการแล้ว'
    extra = []
    if payer_name: extra.append(f'👤 โดย: {payer_name}')
    if tx.get('split_mode') in ('equal','percent','custom'): extra.append('🤝 รายการนี้เป็นค่าใช้จ่ายร่วม')
    body=[
        _txt(title,'lg','#3A2A30','bold'),
        {'type':'separator','margin':'md'},
        _txt(f"{'💵' if is_income else '🍽️'}  {merchant}",'md','#3B3338','bold',True,'md'),
        _txt(f"฿{float(tx.get('amount') or 0):,.0f}",'xl',amount_color,'bold',False,'sm'),
        _txt(f'📅 {occurred}  ·  🏷️ {category}','xs','#7A6D74',None,True,'sm'),
    ]
    body += [_txt(x,'xs','#7A6D74',None,True,'sm') for x in extra]
    body.append(_txt(f"🆔 #{tx.get('id','-')}",'xs','#AAA0A6',None,False,'sm'))
    return {'type':'flex','altText':f"{'รับ' if is_income else 'จ่าย'} {_money(tx.get('amount'))}",
            'contents':{'type':'bubble','size':'kilo','body':{'type':'box','layout':'vertical','contents':body,
                'paddingAll':'18px','backgroundColor':'#FFFFFF'}}}


def summary_flex(s, household=None):
    month=s.get('month','')
    title=f'📊 สรุปเดือนนี้'
    if household: title += f"\n🏠 {household.get('name','')}"
    cats=s.get('categories',[])[:6]
    total_exp=sum(float(c.get('total') or 0) for c in cats) or 1
    cat_colors=['#F45B83','#F29C62','#8EC7EE','#9C7AD9','#F1C95B','#B9B9C4']
    body=[_txt(title,'xl','#3A2A30','bold',True),_txt(f"{month}  ·  {s.get('count',0)} รายการ",'xs','#8A7F88',None,False,'sm'),
          {'type':'box','layout':'horizontal','spacing':'sm','margin':'md','contents':[
              _metric('💰 รายรับ',_money(s.get('income')), '#E5F7EC'),
              _metric('💸 รายจ่าย',_money(s.get('expense')), '#FFF0F4'),
              _metric('💚 คงเหลือ',_money(s.get('balance')), '#E6F3FD')
          ]},
          _txt('รายจ่ายตามหมวด','md','#3A2A30','bold',False,'lg')]
    for i,c in enumerate(cats):
        pct=float(c.get('total') or 0)/total_exp*100
        body.append({'type':'box','layout':'horizontal','margin':'sm','contents':[
            _txt(c.get('category','อื่นๆ'),'xs','#4D454A',None,False,None,4),
            _txt(_money(c.get('total')),'xs','#3B3338','bold',False,None,2,'end'),
            _txt(f'{pct:.1f}%','xs','#8A7F88',None,False,None,1,'end')
        ]})
        body.append({'type':'box','layout':'horizontal','height':'6px','backgroundColor':'#F1EDF0','cornerRadius':'6px','contents':[
            {'type':'box','layout':'vertical','width':f'{max(2,min(100,pct))}%','backgroundColor':cat_colors[i%len(cat_colors)],'cornerRadius':'6px','contents':[]}
        ]})
    body.append({'type':'box','layout':'horizontal','spacing':'sm','margin':'lg','contents':[
        {'type':'button','style':'secondary','height':'sm','flex':1,'action':{'type':'message','label':'ดูรายละเอียด','text':'รายการล่าสุด'}},
        {'type':'button','style':'primary','height':'sm','color':'#A9D5F5','flex':1,'action':{'type':'message','label':'รายการล่าสุด','text':'รายการล่าสุด'}}
    ]})
    return {'type':'flex','altText':'สรุปเดือนนี้','contents':{'type':'bubble','size':'giga','body':{'type':'box','layout':'vertical','contents':body,'paddingAll':'18px'}}}


def recent_flex(rows, household=None):
    title='📋 รายการล่าสุด (10 รายการ)'
    if household: title += f"\n🏠 {household.get('name','')}"
    body=[_txt(title,'lg','#3A2A30','bold',True)]
    icons={'อาหาร':'🍽️','เครื่องดื่ม':'☕','ของใช้':'🛒','เดินทาง':'🚗','ช้อปปิ้ง':'🛍️','บันเทิง':'🎬','บ้าน':'🏠'}
    for i,r in enumerate(rows[:10],1):
        sign='+' if r.get('type')=='income' else '-'
        color='#16844A' if sign=='+' else '#3B3338'
        name=r.get('merchant') or r.get('note') or r.get('category') or 'รายการ'
        cat=r.get('category') or 'อื่นๆ'
        date=str(r.get('occurred_at') or '')[:10]
        body.append({'type':'box','layout':'horizontal','margin':'md','alignItems':'center','contents':[
            _txt(str(i),'xs','#9A9096',None,False,None,1),
            _txt(icons.get(cat,'📦'),'md','#3B3338',None,False,None,1),
            {'type':'box','layout':'vertical','flex':5,'contents':[_txt(name,'sm','#3B3338','bold',True),_txt(f'{cat} · {date}','xs','#9A9096')]},
            _txt(f'{sign}{_money(r.get("amount"))}','sm',color,'bold',False,None,2,'end')
        ]})
    body.append({'type':'box','layout':'horizontal','spacing':'sm','margin':'lg','contents':[
        {'type':'button','style':'secondary','height':'sm','action':{'type':'message','label':'สรุปเดือนนี้','text':'สรุปเดือนนี้'}},
        {'type':'button','style':'secondary','height':'sm','action':{'type':'message','label':'เพิ่มรายการ','text':'เพิ่มรายการ'}}
    ]})
    return {'type':'flex','altText':'รายการล่าสุด','contents':{'type':'bubble','size':'giga','body':{'type':'box','layout':'vertical','contents':body,'paddingAll':'18px'}}}


def household_flex(households, active=None):
    body=[_txt('🏠 บ้านของฉัน','xl','#3A2A30','bold'),_txt('เลือกบ้านที่ต้องการใช้งาน','sm','#8A7F88',None,False,'sm')]
    for i,h in enumerate(households,1):
        active_now=active and h.get('id')==active.get('id')
        name=h.get('name','บ้านของเรา')
        label=f'{i}. 🏠 {name}' + ('  ⭐ ใช้งานอยู่' if active_now else '')
        body.append({'type':'box','layout':'horizontal','margin':'md','backgroundColor':'#FFF8FB' if active_now else '#FFFFFF','cornerRadius':'14px','paddingAll':'10px','contents':[
            {'type':'box','layout':'vertical','flex':5,'contents':[_txt(label,'sm','#3B3338','bold',True),_txt(f"รหัส {h.get('invite_code','-')}",'xs','#9A9096')]},
            {'type':'button','style':'secondary','height':'sm','flex':2,'action':{'type':'message','label':'เลือก','text':f"ใช้บัญชี {name}"}}
        ]})
    body += [
        {'type':'button','style':'primary','color':'#FF9FBD','height':'sm','margin':'lg','action':{'type':'message','label':'สร้างบ้านใหม่','text':'สร้างบ้าน'}},
        {'type':'button','style':'secondary','height':'sm','margin':'sm','action':{'type':'message','label':'เปลี่ยนชื่อบ้าน','text':'เปลี่ยนชื่อบ้าน'}},
        {'type':'button','style':'secondary','height':'sm','margin':'sm','action':{'type':'message','label':'ลบบ้าน','text':'ลบบ้าน'}}
    ]
    return {'type':'flex','altText':'บ้านของฉัน','contents':{'type':'bubble','size':'giga','body':{'type':'box','layout':'vertical','contents':body,'paddingAll':'18px'}}}


def settlement_flex(data):
    contents=[_txt(f"🤝 สรุปค่าใช้จ่ายร่วม {data.get('month','')}",'lg','#3A2A30','bold')]
    for m in data.get('members',[]):
        status='ควรได้รับ' if m['net']>0.005 else ('ควรจ่ายเพิ่ม' if m['net']<-0.005 else 'พอดี')
        contents.append({'type':'box','layout':'vertical','margin':'md','backgroundColor':'#FFF8FB','cornerRadius':'12px','paddingAll':'10px','contents':[
            _txt(m['name'],'sm','#3B3338','bold'),_txt(f"จ่าย {_money(m['paid'])} · รับผิดชอบ {_money(m['owed'])}",'xs','#7A6D74'),_txt(status if abs(m['net'])<=0.005 else f"{status} {_money(abs(m['net']))}",'xs','#D94B6A' if m['net']<0 else '#16844A','bold')
        ]})
    contents.append(_txt('💸 ใครต้องโอนให้ใคร','md','#3A2A30','bold',False,'lg'))
    if data.get('transfers'):
        for t in data['transfers']:
            contents.append(_txt(f"{t['from_name']} → {t['to_name']}  {_money(t['amount'])}",'sm','#3B3338',None,True,'sm'))
    else:
        contents.append(_txt('✅ ยอดเคลียร์กันแล้ว','sm','#16844A','bold'))
    return {'type':'flex','altText':'สรุปค่าใช้จ่ายร่วม','contents':{'type':'bubble','body':{'type':'box','layout':'vertical','contents':contents,'paddingAll':'18px'}}}


def help_text():
    return '''🐰 MeeTang — มีตังค์ ไม่งงเรื่องเงิน

💰 บันทึกเงิน
• กินข้าว 120
• กาแฟ 75
• เงินเดือน 30000

📊 ดูเงิน
• สรุป
• สรุปเดือนนี้
• รายการล่าสุด

🏠 หลายบ้าน
• บ้านของฉัน
• สร้างบ้าน ร้านขนม
• ใช้บัญชี ร้านขนม
• เปลี่ยนชื่อบ้าน บ้านใหม่
• ลบบ้าน
• ออกจากบ้าน

🤝 บัญชีร่วม
• สมาชิก
• ค่าอาหาร 600 หารครึ่ง
• ใครจ่าย
• เคลียร์ยอด

🗑️ ลบรายการ
• ลบ 123

📸 สลิป
ส่งรูปได้ แต่โหมดฟรียังไม่อ่านยอดจากรูปอัตโนมัติครับ'''
