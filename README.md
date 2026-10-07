# MeeTang — Free Edition 💰

LINE Bot รายรับ-รายจ่ายแบบไม่ใช้ OpenAI API และไม่ต้องใส่ OPENAI_API_KEY

## ทำได้
- พิมพ์ `กินข้าว 120` → บันทึกรายจ่าย
- `เงินเดือนเข้า 30000` → บันทึกรายรับ
- `ค่าไฟ 1200 หารครึ่ง` → หารค่าใช้จ่ายร่วม
- `สร้างบ้าน` / `เข้าร่วม CODE` → บัญชีร่วม
- `สรุปเดือนนี้` / `รายการล่าสุด` / `สรุปค่าใช้จ่ายร่วม`
- Dashboard และ Rich Menu

## ข้อจำกัด Free Edition
- ไม่มี AI/vision API
- ส่งรูปสลิปได้ แต่บอทจะขอให้พิมพ์ยอด เพราะการอ่านรูปอัตโนมัติต้องใช้ OCR/vision service เพิ่ม
- SQLite บน Render Free เป็นพื้นที่ชั่วคราวและข้อมูลอาจหายเมื่อ service ถูกสร้างใหม่/redeploy; หากต้องการเก็บข้อมูลจริงควรต่อฐานข้อมูล Free tier ภายนอกภายหลัง

## Environment Variables
- `LINE_CHANNEL_SECRET`
- `LINE_CHANNEL_ACCESS_TOKEN`
- `TZ=Asia/Bangkok`
- `DATABASE_PATH=moneymate.db`

ไม่ต้องมี `OPENAI_API_KEY`

## Deploy
Build:
`pip install -r requirements.txt`

Start:
`uvicorn app:app --host 0.0.0.0 --port $PORT`

Webhook:
`https://YOUR-RENDER-DOMAIN/webhook`


## UI / หลายบ้าน
- Rich Menu 6 ปุ่ม: เพิ่มรายการ / สรุปเงิน / รายการล่าสุด / บ้านของฉัน / เคลียร์ยอด / วิธีใช้
- Dashboard เลือกบ้านจาก dropdown ได้ และดูรายรับ-รายจ่ายแยกตามบ้าน
- ใน LINE พิมพ์ `รหัสของฉัน` เพื่อรับ LINE User ID สำหรับเชื่อม Dashboard
- สร้าง/สลับ/เปลี่ยนชื่อ/ลบบ้านได้จาก LINE และ Dashboard
