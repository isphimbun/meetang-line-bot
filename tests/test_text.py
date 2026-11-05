import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from textutil import normalize_text as n, is_dashboard_request as d

def test_double_sara_e_normalized():
    assert n('เปิดเเดชบอร์ด')=='เปิดแดชบอร์ด' and n('  เเก้   ไข ')=='แก้ ไข' and n('กิน\u200bข้าว 120')=='กินข้าว 120'

def test_dashboard_variants_accepted():
    for t in ['เปิดแดชบอร์ด','เปิดเเดชบอร์ด','เปิดเเดชบอด','เปิด แดชบอร์ด','แดชบอร์ด','เเดชบอร์ด','dashboard','Dashboard','login','ล็อกอิน','เข้าเว็บ','เปิดแดชบอร์ดหน่อย']:
        assert d(t), t

def test_normal_messages_not_hijacked():
    for t in ['กินข้าว 120','บ้าน ค่าน้ำ 320','ผ่อน เครื่องซักผ้า 1500','จ่ายงวดบ้าน 20000','เมนู','สรุป','ซื้อกระดานแดชบอร์ด 500','']:
        assert not d(t), t

if __name__=='__main__':
    for k,v in list(globals().items()):
        if k.startswith('test_'): v(); print('ok',k)
