import re

def member_map(household, user_id):
    out={}
    members=(household or {}).get('members',[])
    for i,m in enumerate(members):
        names=[m.get('display_name') or '', m.get('user_id','')]
        if i==0: names += ['คนแรก']
        if m.get('user_id')==user_id: names += ['ฉัน','เรา','ตัวเอง']
        for n in names:
            n=n.strip().lower()
            if n: out[n]=m['user_id']
    # In a two-person household, "แฟน" is the other member.
    if len(members)==2:
        other=next((m['user_id'] for m in members if m['user_id']!=user_id), None)
        if other: out['แฟน']=other
    return out

def parse_split_instruction(text, household, user_id):
    """Return (mode, participants, amounts, human_note) or None.
    Supports equal, percentages and explicit THB amounts.
    Examples: 'ค่าไฟ 1200 หารครึ่ง', 'ฉัน 40% แฟน 60%', 'ฉัน 400 แฟน 800'.
    """
    if not household: return None
    members=household.get('members',[])
    if len(members)<2: return None
    low=text.lower()
    names=member_map(household,user_id)
    # Equal split phrases
    if re.search(r'หาร\s*(ครึ่ง|2|สอง)|50\s*/\s*50|คนละ\s*ครึ่ง|หารเท่า(?:กัน|ๆกัน)', low):
        return 'equal',[m['user_id'] for m in members],None,'หารเท่ากัน'
    # Ratio split by order: "หาร 60:40", "60/40", "หาร 50:30:20".
    ratio_match = re.search(r'(?:หาร\s*)?(\d+(?:\.\d+)?(?:\s*[:/]\s*\d+(?:\.\d+)?)+)(?:\s*%?)', low)
    if ratio_match:
        vals=[float(x) for x in re.split(r'\s*[:/]\s*', ratio_match.group(1))]
        if len(vals) == len(members) and abs(sum(vals)-100) < 0.01:
            p=[m['user_id'] for m in members]
            return 'percent',p,{uid:v for uid,v in zip(p,vals)},'แบ่งตามสัดส่วน ' + ':'.join(str(int(v) if v.is_integer() else v) for v in vals)

    # Named percentage split: "ฉัน 60% แฟน 40%".
    pct=[]
    for m in re.finditer(r'([\u0E00-\u0E7Fa-zA-Z0-9_]+)\s*(\d+(?:\.\d+)?)\s*%', low):
        label=m.group(1); val=float(m.group(2)); uid=names.get(label)
        if uid: pct.append((uid,val))
    if len(pct)>=2 and abs(sum(v for _,v in pct)-100)<0.01:
        return 'percent',[uid for uid,_ in pct],{uid:v for uid,v in pct},'แบ่งตามสัดส่วน'
    # Explicit amount split: e.g. ฉัน 400 แฟน 800
    pairs=[]
    for m in re.finditer(r'([\u0E00-\u0E7Fa-zA-Z0-9_]+)\s*(\d+(?:[.,]\d+)?)\s*(?:บาท)?', low):
        label=m.group(1); val=float(m.group(2).replace(',','')); uid=names.get(label)
        if uid: pairs.append((uid,val))
    if len(pairs)>=2:
        amounts={uid:v for uid,v in pairs}
        return 'custom',[uid for uid,_ in pairs],amounts,'แบ่งตามจำนวนเงิน'
    return None
