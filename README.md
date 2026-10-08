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
