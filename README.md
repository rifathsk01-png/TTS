# 🎙 Voice Generator Telegram Bot

A Telegram bot that converts text to voice offline using `pyttsx3`,
tracks points, handles withdrawals, and includes a full admin system.
Backed by Firebase Firestore and deployable on Railway.

## Setup

### 1. Firebase
- Go to Firebase Console → Create project
- Enable Firestore Database
- Go to Project Settings → Service Accounts → Generate New Private Key
- Copy the JSON content into your `.env` as `FIREBASE_CREDENTIALS`

### 2. Telegram Bot
- Create a bot via @BotFather → copy the token into `BOT_TOKEN`
- Get your numeric Telegram ID (use @userinfobot) → set as `ADMIN_ID`

### 3. Local Development
```bash
pip install -r requirements.txt
python main.py
