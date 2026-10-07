# MeeTang v8 — Command Manager + Safe Database Backup

## Important
This version is designed to be non-destructive to the existing SQLite database. It does **not** delete or reset `moneymate.db` and uses `CREATE TABLE IF NOT EXISTS` migrations.

### Dashboard
- 🤖 Command Manager: add/edit/enable/disable/delete bot commands without redeploying.
- 💾 Database backup: `/api/backup/database` downloads a copy of the live SQLite DB.
- 🔎 Backup status: `/api/backup/status` reports whether the configured DB file exists and its size.

### Default commands
- ฝากเงิน / ฝาก → income
- ถอนเงิน / ถอน → expense
- เงินเดือน → income
- สรุป → summary
- รายการล่าสุด → recent
- ลบรายการล่าสุด → delete latest

## Critical Render warning
If this service uses Render ephemeral filesystem, a redeploy/restart can remove local SQLite files. Do not assume the database survives deployment. Before a production migration, use the backup endpoint on the currently running version if it exists, or migrate the data to persistent external storage.

## Required environment variables
- LINE_CHANNEL_SECRET
- LINE_CHANNEL_ACCESS_TOKEN (or LINE_ACCESS_TOKEN)
