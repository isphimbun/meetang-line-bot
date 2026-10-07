# MeeTang — Free Multi-House v5

MeeTang is a LINE finance bot with a pastel kawaii Rich Menu and a matching web Dashboard.

## Included
- LINE text expense/income entry
- Monthly summary and recent transactions as Flex messages
- Multiple households / accounts
- Create, switch, rename, delete, and leave households
- Shared expense settlement
- Free mode: receipt images are accepted, but automatic OCR/AI extraction is disabled
- Pastel 6-button Rich Menu matching the MeeTang visual design
- Matching web Dashboard at `/`

## Required Render environment variables
- `LINE_CHANNEL_SECRET`
- `LINE_CHANNEL_ACCESS_TOKEN`

`LINE_ACCESS_TOKEN` is also accepted for compatibility.

## Render start command
`uvicorn app:app --host 0.0.0.0 --port $PORT`

## Rich Menu
The app creates/activates `MeeTang Main Menu v5` automatically on startup. LINE Rich Menus are created through the Messaging API; the menu image is uploaded and then set as the default menu.

## Dashboard
Open the Render service root URL, for example `https://your-service.onrender.com/`.
The first time, enter the LINE User ID returned by the bot command `รหัสของฉัน`.
