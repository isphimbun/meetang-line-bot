import json

def _money(v): return f'฿{float(v):,.2f}'

def summary_flex(s, household=None):
    title = f"📊 สรุป {s['month']}" + (f"\n🏠 {household['name']}" if household else '')
    cats = s.get('categories', [])[:6]
    lines = [{'type':'text','text':title,'weight':'bold','size':'xl'},
             {'type':'separator','margin':'md'},
             {'type':'box','layout':'horizontal','margin':'md','contents':[
                 {'type':'text','text':'รายรับ','size':'sm','color':'#555555'}, {'type':'text','text':_money(s['income']),'align':'end','weight':'bold'}]},
             {'type':'box','layout':'horizontal','contents':[
                 {'type':'text','text':'รายจ่าย','size':'sm','color':'#555555'}, {'type':'text','text':_money(s['expense']),'align':'end','weight':'bold'}]},
             {'type':'box','layout':'horizontal','contents':[
                 {'type':'text','text':'คงเหลือ','weight':'bold'}, {'type':'text','text':_money(s['balance']),'align':'end','weight':'bold'}]},
             {'type':'separator','margin':'md'}, {'type':'text','text':'ใช้จ่ายตามหมวด','weight':'bold','margin':'md'}]
    for c in cats:
        lines.append({'type':'box','layout':'horizontal','margin':'sm','contents':[{'type':'text','text':c['category'],'size':'sm'}, {'type':'text','text':_money(c['total']),'align':'end','size':'sm'}]})
    return {'type':'flex','altText':f"สรุป {s['month']}",'contents':{'type':'bubble','body':{'type':'box','layout':'vertical','contents':lines}}}

def transaction_flex(tx, household=None, payer_name=None):
    shared = tx.get('split_mode') == 'equal'
    extra = f"\n👤 คนจ่าย: {payer_name}" if payer_name else ''
    if shared: extra += '\n🤝 หารเท่ากันกับสมาชิก'
    elif tx.get('split_mode') in ('percent','custom'): extra += '\n🤝 แบ่งค่าใช้จ่ายตามสัดส่วน'
    text = f"{'💰 รายรับ' if tx['type']=='income' else '💸 รายจ่าย'}\n{_money(tx['amount'])} — {tx.get('category','อื่นๆ')}\n{tx.get('merchant') or tx.get('note') or '-'}{extra}\n🆔 #{tx['id']}"
    return {'type':'text','text':text}

def recent_flex(rows, household=None):
    title = '📋 รายการล่าสุด' + (f"\n🏠 {household['name']}" if household else '')
    contents=[{'type':'text','text':title,'weight':'bold','size':'lg'}]
    for r in rows[:10]:
        sign='+' if r['type']=='income' else '-'; split=' 🤝' if r.get('split_mode')=='equal' else ''
        contents.append({'type':'text','text':f"#{r['id']} {sign}{_money(r['amount'])} {r['category']}{split}\n{r.get('merchant') or r.get('note') or ''}", 'margin':'md','wrap':True})
    return {'type':'flex','altText':'รายการล่าสุด','contents':{'type':'bubble','body':{'type':'box','layout':'vertical','contents':contents}}}

def settlement_flex(data):
    contents=[{'type':'text','text':f"🤝 สรุปค่าใช้จ่ายร่วม {data['month']}",'weight':'bold','size':'lg'}]
    for m in data['members']:
        status = 'ควรได้รับ' if m['net'] > 0.005 else ('ควรจ่ายเพิ่ม' if m['net'] < -0.005 else 'พอดี')
        contents.append({'type':'box','layout':'vertical','margin':'md','contents':[
            {'type':'text','text':m['name'],'weight':'bold'},
            {'type':'text','text':f"จ่าย {_money(m['paid'])} • รับผิดชอบ {_money(m['owed'])}"},
            {'type':'text','text':f"{status} {_money(abs(m['net']))}" if abs(m['net'])>0.005 else 'ยอดตรงกันแล้ว'}
        ]})
    if data.get('transfers'):
        contents.append({'type':'separator','margin':'md'})
        contents.append({'type':'text','text':'💸 ใครต้องโอนให้ใคร','weight':'bold','margin':'md'})
        for t in data['transfers']:
            contents.append({'type':'text','text':f"{t['from_name']} → {t['to_name']}  {_money(t['amount'])}",'margin':'sm','wrap':True})
    else:
        contents.append({'type':'separator','margin':'md'})
        contents.append({'type':'text','text':'✅ ยอดเคลียร์กันแล้ว','margin':'md'})
    return {'type':'flex','altText':'สรุปค่าใช้จ่ายร่วม','contents':{'type':'bubble','body':{'type':'box','layout':'vertical','contents':contents}}}

def help_text():
    return '''💰 MoneyMate\n\nพิมพ์ได้เลย เช่น\n• กินข้าว 120\n• เงินเดือนเข้า 30000\n• ค่าไฟ 1200 หารครึ่ง\n\nคำสั่งร่วม:\n• ตั้งชื่อ มะลิ\n• สร้างบ้าน\n• เข้าร่วม ABC123\n• บัญชีของฉัน\n• ใช้บัญชี 1\n• สรุปค่าใช้จ่ายร่วม\n• รายการล่าสุด\n• ลบ 123\n\n📸 ส่งรูปสลิปเพื่อให้ AI อ่านยอดให้ได้เลย'''
