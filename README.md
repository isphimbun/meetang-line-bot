# MeeTang v10 — บ้าน & สินเชื่อ + รายการผ่อน

เวอร์ชันนี้ต่อจาก v9 และเพิ่มโมดูลเต็มสำหรับคนที่ได้รับสิทธิ์จาก Admin:

- 🏠 บ้าน & สินเชื่อ
  - ข้อมูลราคาซื้อ / วงเงินกู้ / ค่างวด / ธนาคาร / ระยะเวลากู้
  - ตารางดอกเบี้ยหลายช่วง รองรับ Fix และ MRR +/− Offset
  - คำนวณเงินต้นและดอกเบี้ยประมาณการรายงวด
  - กราฟแนวโน้มเงินต้นคงเหลือ
  - บันทึกค่างวดจริงและเงินโปะ
  - 🛡️ ประกันแยกจากสินเชื่อ เช่น MRTA / ประกันอัคคีภัย
  - 🧾 ค่าใช้จ่ายบ้านแยกหมวด เช่น ค่าน้ำ ค่าไฟ อินเทอร์เน็ต ค่าส่วนกลาง ค่าซ่อม
- 💳 รายการผ่อน
  - เพิ่มสินค้า/บริการที่ผ่อน
  - จำนวนงวด / ค่างวด / ยอดคงเหลือ
  - บันทึกการจ่ายแต่ละงวด
- 👑 สิทธิ์สมาชิกแบบ household-level จาก v9
  - Owner/Admin เปิด/ปิด loan และ installment ให้สมาชิกแต่ละคน
  - Backend ตรวจสิทธิ์ด้วย ไม่ใช่แค่ซ่อนเมนู
- 🤖 Command Manager และ backup จาก v9 ยังคงอยู่

## Deploy
Start command:
`uvicorn app:app --host 0.0.0.0 --port $PORT`

Environment:
- LINE_CHANNEL_SECRET
- LINE_CHANNEL_ACCESS_TOKEN (หรือ LINE_ACCESS_TOKEN)
- DATABASE_PATH (ถ้าต้องการกำหนด path เอง)

## สำคัญ
ก่อน Deploy ให้ดาวน์โหลด backup ฐานข้อมูลจาก Dashboard ในเมนูตั้งค่า Admin ก่อนเสมอ โดยเฉพาะถ้าใช้ SQLite บน Render Free ซึ่ง filesystem อาจไม่ถาวรเมื่อมี restart/redeploy.

## Super Admin feature control
Set `SUPER_ADMIN_USER_ID` to the one LINE User ID that owns the MeeTang system. Only this user can open/close `loan` (🏠 บ้าน & สินเชื่อ) and `installment` (💳 รายการผ่อน) for individual users. Household admins no longer control these two global features.

## Super Admin feature control
Set `SUPER_ADMIN_USER_ID` to the one LINE User ID that owns the MeeTang system. Only this user can open/close `loan` (🏠 บ้าน & สินเชื่อ) and `installment` (💳 รายการผ่อน) for individual users. Household admins do not control these global features.


## v12 loan fix
- บ้านและ MRTA เป็นคนละวงเงิน
- MRTA รองรับผ่อนแยกและใช้อัตราดอกเบี้ยเดียวกับสินเชื่อบ้าน
- มีตารางผ่อน/บันทึกงวดประกันแยก
- ป้องกันค่างวดบ้านต่ำกว่าดอกเบี้ยเดือนแรก
- เว้นค่างวดบ้านว่างได้เพื่อให้ระบบประมาณการจากดอกเบี้ยแรกและระยะเวลา


## v25 changes
- Rich Menu bottom-right button opens DASHBOARD_URL (default: https://meetang-bot.onrender.com)
- Split expenses support ratio syntax such as `หาร 60:40`, `60/40`, and named percentages.
- Added examples to LINE help.

## v26 fix
- Fixed PostgreSQL summary query: category + type are both included in GROUP BY.

## v26.1 Rich Menu
- Bottom-right Rich Menu panel visibly says Dashboard.
- The panel action opens DASHBOARD_URL (default https://meetang-bot.onrender.com).

## v27
- Fix PostgreSQL boolean permissions: write TRUE/FALSE instead of 1/0.

## Rich Menu Dashboard
- Bottom-right Rich Menu button opens DASHBOARD_URL.
- Default: https://meetang-bot.onrender.com

## Final Rich Menu
Top: เพิ่มรายการ | รายการล่าสุด | สรุปเงิน
Bottom: บ้านของฉัน | เคลียร์ยอด | Dashboard
Dashboard opens DASHBOARD_URL (default: https://meetang-bot.onrender.com).

## v29 Rich Menu Fix
- The app no longer reuses the old v5 Rich Menu.
- Every deployment creates a fresh v29 menu, uploads the approved pastel bunny artwork, and sets it as the default for all users.
- Bottom-right Dashboard opens DASHBOARD_URL (default https://meetang-bot.onrender.com).

## v30 Rich Menu Fix
- Explicitly links the new Rich Menu to every user in the database so old user-specific menus are replaced.

## v31 Rich Menu Image Fix
LINE Rich Menu images must be <= 1 MB. The approved artwork is compressed to JPEG (517,622 bytes, quality 88) and the uploader uses image/jpeg.

## v34 fix
- แก้ INSERT ไม่คืนค่า id (ตรวจ `RETURNING id` ผิดตัวพิมพ์) ทำให้บันทึกรายการ/สร้างบ้าน/บันทึกสินเชื่อใหม่ล้มเหลว
- แก้ `enabled=1` กับคอลัมน์ boolean ใน bot_commands ทำให้บอทไม่ตอบข้อความ
- แก้ SQL ผิดใน get_all_user_ids
- แปลงค่า DATE/NUMERIC จาก PostgreSQL เป็น string/float (กัน `/api/loan` พัง)
- ช่องวันที่/ตัวเลขที่เว้นว่างบันทึกเป็น NULL
- Rich Menu ตั้งค่าแบบ background ไม่บล็อกการเปิดเซิร์ฟเวอร์
- ตารางประมาณการหลังงวดจริงเริ่มเดือนถัดไป (เดิมซ้ำเดือน)

## v35 แจ้งเตือนสมาชิกในบ้าน
เมื่อมีคนในบ้านบันทึกข้อมูล บอทจะส่ง LINE (Flex) หาสมาชิกคนอื่นในบ้านเดียวกัน (ไม่ส่งหาคนที่บันทึกเอง):
- 🏠 รายการรายรับ/รายจ่ายใหม่ (พิมพ์ข้อความ / คำสั่ง / สลิป)
- 💳 บันทึกจ่ายงวดผ่อน (รายการ, ยอดงวดนี้, จำนวนงวด x/y)
- 🏡 บันทึกชำระสินเชื่อบ้าน (ยอดชำระ, เงินต้น, ดอกเบี้ย)
- 🧾 ค่าใช้จ่ายบ้าน (ค่าน้ำ ค่าไฟ เน็ต ส่วนกลาง ซ่อม)
- 🛡️ จ่ายงวดประกัน (MRTA / อัคคีภัย แบบผ่อนแยก)

ไฟล์ใหม่: `notify.py` — ส่งแบบ background ถ้าส่งไม่สำเร็จจะไม่กระทบการบันทึกข้อมูล
ปิดทั้งระบบ: ตั้ง `NOTIFY_MEMBERS=0`
หมายเหตุ: ข้อความ multicast นับเป็นโควตาข้อความของ LINE OA ตามจำนวนผู้รับ

## แชท LINE สำหรับ Dashboard (v35)
คำสั่ง (ต้องมีสิทธิ์ loan/installment เหมือน Dashboard): `บ้าน ค่าน้ำ 320` · `จ่ายงวดบ้าน 20000 [โปะ 5000]` · `ผ่อน เครื่องซักผ้า [1500]` · `จ่ายประกัน MRTA [1500]`
โค้ดอยู่ใน `chat_actions.py` ยอดที่พิมพ์ใน "จ่ายงวดบ้าน" คือยอดจ่ายทั้งหมด ส่วนโปะรวมอยู่ในยอดนั้น (เหมือน Dashboard)


## v38 — แก้การคำนวณ + ความปลอดภัย + ฟีเจอร์ใหม่
**การคำนวณ (ตรวจเทียบใบแจ้งหนี้จริงแล้ว: 3,160,000 @2.1% → 1,999.89 / 5,604.66 / 5,946.52 ตรงทุกงวด)**
- ดอกเบี้ย = ยอดต้นคงเหลือ × อัตรา × จำนวนวันจริง ÷ 365 **ปัดเศษใกล้สุด** (v37 ตัดทิ้ง ทำให้คลาด 1 สตางค์)
- อัตราเปลี่ยนกลางงวด/กลางเดือน คิดแยกตามวันจริง; ช่วงดอกเบี้ยกำหนดเป็น "จำนวนเดือน" ได้ถึง 6 ช่วง (เดิมล็อก 1 ปี/ช่วง และถ้าไม่มีช่วงครอบคลุมจะคิด 0%)
- ตั้งวิธีนับวันได้: ÷365 / ÷360 / ÷365-366 ตามปี
- "ยอดคงเหลือ ณ วันที่เริ่มใช้งาน" สำหรับคนกู้มานานแล้ว
- ปุ่มคำนวณใหม่ไม่ทับงวดที่กรอกดอกเบี้ย/เงินต้นเอง (manual)
- รายการผ่อน: เลือกวิธีคิดดอกเบี้ย (ลดต้นลดดอก / flat / ไม่มี) และคำนวณเงินต้น-ดอกเบี้ยให้
- เตือนเมื่อค่างวดไม่พอจ่ายดอกเบี้ย
- คอลัมน์ใหม่ถูกเพิ่มอัตโนมัติตอนเริ่มระบบ (`ensure_schema`) ไม่ต้องรัน SQL เอง

**ความปลอดภัย** — Dashboard เข้าด้วยลิงก์จาก LINE (พิมพ์ "เปิดแดชบอร์ด") ไม่ต้องพิมพ์ User ID อีก; เซิร์ฟเวอร์บังคับ user_id จาก token
ต้องตั้ง `DASH_SECRET` (สตริงสุ่มยาวๆ) หรือใช้ `LINE_CHANNEL_SECRET` ที่มีอยู่ ปิดชั่วคราวด้วย `DASH_AUTH=0`

**ฟีเจอร์ใหม่** — แจ้งเตือนค่างวดบ้าน/ผ่อน/ประกัน/อัตราดอกเบี้ยเปลี่ยน อัตโนมัติ (`reminders.py`, ตั้งเวลา `REMINDER_HOUR`, ปิด `REMINDERS=0`);
จำลองโปะเพิ่ม; กราฟเงินต้น vs ดอกเบี้ย; ส่งออก CSV; แถบโหลดบางๆ แทนการบังหน้าจอ

**ทดสอบ** — `python tests/test_calc.py`, `tests/test_auth.py`, `tests/test_reminders.py`
