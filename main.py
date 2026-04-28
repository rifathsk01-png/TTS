import os
import io
import asyncio
import tempfile
import logging

import pyttsx3
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import (
    Message,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
)
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import TelegramForbiddenError

import firebase as db

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
ADMIN_ID: int = int(os.getenv("ADMIN_ID", "0"))
ADMIN_USERNAME: str = "Sefuax"
MIN_WITHDRAW_POINTS: int = 10_000
POINTS_PER_GENERATION: int = 2
MIN_WORDS: int = 10

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set in environment variables.")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)


# ─────────────────────────────────────────────
# FSM States
# ─────────────────────────────────────────────

class TTSStates(StatesGroup):
    choosing_language = State()
    choosing_gender = State()
    waiting_for_text = State()


class WithdrawStates(StatesGroup):
    choosing_method = State()
    waiting_for_address = State()


# ─────────────────────────────────────────────
# Keyboards
# ─────────────────────────────────────────────

def main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎙 Text To Voice"), KeyboardButton(text="📊 Total Info / Points")],
            [KeyboardButton(text="💰 Withdraw"),      KeyboardButton(text="👨‍💻 Admin")],
        ],
        resize_keyboard=True,
    )


def language_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🇧🇩 Bangla"), KeyboardButton(text="🇬🇧 English")],
            [KeyboardButton(text="🔙 Back")],
        ],
        resize_keyboard=True,
    )


def gender_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="👨 Male"), KeyboardButton(text="👩 Female")],
            [KeyboardButton(text="🔙 Back")],
        ],
        resize_keyboard=True,
    )


def withdraw_method_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📱 bKash"), KeyboardButton(text="💎 Binance")],
            [KeyboardButton(text="🔙 Back")],
        ],
        resize_keyboard=True,
    )


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID


async def _notify_admin_new_user(name: str, username: str, chat_id: int):
    text = (
        "👤 <b>New User Started Bot!</b>\n"
        "━━━━━━━━━━━━━━━\n"
        f"• Name: {name}\n"
        f"• Username: @{username}\n"
        f"• User ID: <code>{chat_id}</code>"
    )
    try:
        await bot.send_message(ADMIN_ID, text, parse_mode="HTML")
    except TelegramForbiddenError:
        logger.warning("Admin has blocked the bot or chat not found.")


def _generate_voice(text: str, language: str, gender: str) -> bytes:
    """
    Generate TTS audio using pyttsx3 and return raw WAV bytes.
    pyttsx3 is synchronous; we run it in a thread via asyncio.
    """
    engine = pyttsx3.init()

    # Gender: pyttsx3 voices — index 0 is often male, 1 female (system-dependent)
    voices = engine.getProperty("voices")
    if gender == "female" and len(voices) > 1:
        engine.setProperty("voice", voices[1].id)
    else:
        engine.setProperty("voice", voices[0].id)

    # Speed adjustment: Bangla text reads slightly slower
    rate = 130 if language == "bangla" else 150
    engine.setProperty("rate", rate)
    engine.setProperty("volume", 1.0)

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = tmp.name

    engine.save_to_file(text, tmp_path)
    engine.runAndWait()
    engine.stop()

    with open(tmp_path, "rb") as f:
        audio_bytes = f.read()

    os.unlink(tmp_path)
    return audio_bytes


async def generate_voice_async(text: str, language: str, gender: str) -> bytes:
    """Run blocking pyttsx3 in a thread pool to avoid blocking the event loop."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _generate_voice, text, language, gender)


def _guard_banned(user_data: dict | None) -> bool:
    """Return True if user is banned or doesn't exist."""
    if user_data is None:
        return True
    return user_data.get("is_banned", False)


# ─────────────────────────────────────────────
# /start
# ─────────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user = message.from_user
    user_data = db.create_user(user.id, user.username or "", user.full_name or "")

    if user_data.get("is_banned"):
        await message.answer("🚫 You are banned from using this bot.")
        return

    # Notify admin only for truly new users (points == 0 and generations == 0)
    if user_data["total_generations"] == 0 and user_data["points"] == 0:
        await _notify_admin_new_user(
            user.full_name or "N/A",
            user.username or "N/A",
            user.id,
        )

    await message.answer(
        "👋 <b>Welcome to Voice Generator Bot</b>\n\n"
        "Convert your text into voice and earn points!",
        reply_markup=main_keyboard(),
        parse_mode="HTML",
    )


# ─────────────────────────────────────────────
# 🎙 Text To Voice Flow
# ─────────────────────────────────────────────

@router.message(F.text == "🎙 Text To Voice")
async def tts_start(message: Message, state: FSMContext):
    user_data = db.get_user(message.from_user.id)
    if _guard_banned(user_data):
        await message.answer("🚫 You are banned from using this bot.")
        return

    await state.set_state(TTSStates.choosing_language)
    await message.answer(
        "🌐 Choose your language:",
        reply_markup=language_keyboard(),
    )


@router.message(TTSStates.choosing_language, F.text.in_(["🇧🇩 Bangla", "🇬🇧 English"]))
async def tts_language_chosen(message: Message, state: FSMContext):
    lang = "bangla" if "Bangla" in message.text else "english"
    await state.update_data(language=lang)
    await state.set_state(TTSStates.choosing_gender)
    await message.answer("🎭 Choose voice gender:", reply_markup=gender_keyboard())


@router.message(TTSStates.choosing_gender, F.text.in_(["👨 Male", "👩 Female"]))
async def tts_gender_chosen(message: Message, state: FSMContext):
    gender = "male" if "Male" in message.text else "female"
    await state.update_data(gender=gender)
    await state.set_state(TTSStates.waiting_for_text)
    await message.answer(
        "✍️ Now send me your text.\n"
        f"<i>Minimum {MIN_WORDS} words required.</i>",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode="HTML",
    )


@router.message(TTSStates.waiting_for_text)
async def tts_receive_text(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    word_count = len(text.split())

    if word_count < MIN_WORDS:
        await message.answer(
            f"⚠️ Your text is too short!\n"
            f"You sent <b>{word_count}</b> word(s), but minimum is <b>{MIN_WORDS}</b>.\n"
            "Please send a longer text.",
            parse_mode="HTML",
        )
        return

    data = await state.get_data()
    language = data.get("language", "english")
    gender = data.get("gender", "male")

    processing_msg = await message.answer("⏳ Generating your voice... please wait.")

    try:
        audio_bytes = await generate_voice_async(text, language, gender)
    except Exception as e:
        logger.error(f"TTS generation failed: {e}")
        await processing_msg.delete()
        await message.answer("❌ Voice generation failed. Please try again.")
        return

    # Update Firebase
    new_points = db.update_points(message.from_user.id, POINTS_PER_GENERATION)
    new_gen_count = db.increment_generation(message.from_user.id)

    await processing_msg.delete()

    audio_file = io.BytesIO(audio_bytes)
    audio_file.name = "voice.wav"

    await message.answer_voice(
        voice=audio_file,  # type: ignore[arg-type]
        caption=(
            f"✅ Voice generated!\n"
            f"🌐 Language: {language.capitalize()} | 🎭 Gender: {gender.capitalize()}\n"
            f"💰 +{POINTS_PER_GENERATION} points earned! Total: <b>{new_points}</b>\n"
            f"🎙 Total generations: <b>{new_gen_count}</b>"
        ),
        parse_mode="HTML",
    )

    await state.clear()
    await message.answer("What would you like to do next?", reply_markup=main_keyboard())


# ─────────────────────────────────────────────
# 📊 Total Info / Points
# ─────────────────────────────────────────────

@router.message(F.text == "📊 Total Info / Points")
async def show_info(message: Message, state: FSMContext):
    await state.clear()
    user_data = db.get_user(message.from_user.id)
    if _guard_banned(user_data):
        await message.answer("🚫 You are banned from using this bot.")
        return

    await message.answer(
        "📊 <b>Your Profile</b>\n"
        "━━━━━━━━━━━━━━━\n"
        f"👤 Username: @{user_data.get('username') or 'N/A'}\n"
        f"🆔 Chat ID: <code>{user_data['user_id']}</code>\n"
        f"💰 Points: <b>{user_data.get('points', 0)}</b>\n"
        f"🎙 Total Generations: <b>{user_data.get('total_generations', 0)}</b>\n"
        f"🔒 Status: {'🚫 Banned' if user_data.get('is_banned') else '✅ Active'}",
        parse_mode="HTML",
        reply_markup=main_keyboard(),
    )


# ─────────────────────────────────────────────
# 💰 Withdraw Flow
# ─────────────────────────────────────────────

@router.message(F.text == "💰 Withdraw")
async def withdraw_start(message: Message, state: FSMContext):
    await state.clear()
    user_data = db.get_user(message.from_user.id)
    if _guard_banned(user_data):
        await message.answer("🚫 You are banned from using this bot.")
        return

    points = user_data.get("points", 0)
    await message.answer(
        f"💰 <b>Withdraw Points</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"Your points: <b>{points}</b>\n"
        f"Minimum withdraw: <b>{MIN_WITHDRAW_POINTS:,}</b> points\n\n"
        + ("Choose your withdrawal method:" if points >= MIN_WITHDRAW_POINTS
           else f"⚠️ You need <b>{MIN_WITHDRAW_POINTS - points:,}</b> more points to withdraw."),
        parse_mode="HTML",
        reply_markup=withdraw_method_keyboard() if points >= MIN_WITHDRAW_POINTS else main_keyboard(),
    )

    if points >= MIN_WITHDRAW_POINTS:
        await state.set_state(WithdrawStates.choosing_method)
        await state.update_data(points=points)


@router.message(WithdrawStates.choosing_method, F.text.in_(["📱 bKash", "💎 Binance"]))
async def withdraw_method_chosen(message: Message, state: FSMContext):
    method = "bkash" if "bKash" in message.text else "binance"
    await state.update_data(method=method)
    await state.set_state(WithdrawStates.waiting_for_address)

    if method == "bkash":
        await message.answer(
            "📱 Enter your <b>bKash phone number</b> (minimum 11 digits):",
            parse_mode="HTML",
            reply_markup=ReplyKeyboardRemove(),
        )
    else:
        await message.answer(
            "💎 Enter your <b>Binance wallet address</b>:",
            parse_mode="HTML",
            reply_markup=ReplyKeyboardRemove(),
        )


@router.message(WithdrawStates.waiting_for_address)
async def withdraw_address_received(message: Message, state: FSMContext):
    address = (message.text or "").strip()
    data = await state.get_data()
    method = data.get("method", "")
    points = data.get("points", 0)
    user = message.from_user

    # Validation
    if method == "bkash":
        digits_only = address.replace("+", "").replace("-", "").replace(" ", "")
        if not digits_only.isdigit() or len(digits_only) < 11:
            await message.answer(
                "⚠️ Invalid bKash number. Must be at least 11 digits.\nPlease try again:"
            )
            return
    else:  # binance
        if len(address) < 10 or " " in address:
            await message.answer(
                "⚠️ Invalid Binance address. Please enter a valid wallet address:"
            )
            return

    # Save to Firebase
    request_id = db.save_withdraw_request(
        user_id=user.id,
        username=user.username or "",
        points=points,
        method=method.upper(),
        address=address,
    )

    # Notify admin
    admin_text = (
        f"💸 <b>New Withdrawal Request</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"👤 User: @{user.username or 'N/A'} (<code>{user.id}</code>)\n"
        f"💰 Points: <b>{points}</b>\n"
        f"📬 Method: <b>{method.upper()}</b>\n"
        f"📍 Address: <code>{address}</code>\n"
        f"🆔 Request ID: <code>{request_id}</code>"
    )
    try:
        await bot.send_message(ADMIN_ID, admin_text, parse_mode="HTML")
    except TelegramForbiddenError:
        logger.warning("Could not notify admin of withdrawal request.")

    await message.answer(
        "✅ <b>Withdrawal request submitted!</b>\n"
        f"Method: <b>{method.upper()}</b>\n"
        f"Address: <code>{address}</code>\n"
        f"Points: <b>{points}</b>\n\n"
        "The admin will process your request shortly.",
        parse_mode="HTML",
        reply_markup=main_keyboard(),
    )
    await state.clear()


# ─────────────────────────────────────────────
# 👨‍💻 Admin Button
# ─────────────────────────────────────────────

@router.message(F.text == "👨‍💻 Admin")
async def admin_info(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        f"👨‍💻 <b>Admin Panel</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"Admin: @{ADMIN_USERNAME}\n\n"
        f"<b>Available Admin Commands:</b>\n"
        f"<code>/add username amount</code> — Add points\n"
        f"<code>/remove username amount</code> — Remove points\n"
        f"<code>/check username</code> — Check user info\n"
        f"<code>/msg username message</code> — Message a user\n"
        f"<code>/broadcast message</code> — Broadcast to all\n"
        f"<code>/ban username</code> — Ban a user\n"
        f"<code>/unban username</code> — Unban a user",
        parse_mode="HTML",
        reply_markup=main_keyboard(),
    )


# ─────────────────────────────────────────────
# Back button (universal)
# ─────────────────────────────────────────────

@router.message(F.text == "🔙 Back")
async def go_back(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("🏠 Main menu:", reply_markup=main_keyboard())


# ─────────────────────────────────────────────
# Admin Commands
# ─────────────────────────────────────────────

@router.message(Command("add"))
async def admin_add_points(message: Message):
    if not _is_admin(message.from_user.id):
        return

    parts = message.text.split(maxsplit=2)
    if len(parts) != 3 or not parts[2].lstrip("-").isdigit():
        await message.answer("Usage: /add {username_or_id} {amount}")
        return

    identifier, amount = parts[1], int(parts[2])
    user_data = db.get_user(identifier)
    if not user_data:
        await message.answer(f"❌ User '{identifier}' not found.")
        return

    current = user_data.get("points", 0)
    db.set_points_direct(user_data["user_id"], current + amount)
    await message.answer(
        f"✅ Added <b>{amount}</b> points to @{user_data.get('username') or user_data['user_id']}.\n"
        f"New balance: <b>{current + amount}</b>",
        parse_mode="HTML",
    )


@router.message(Command("remove"))
async def admin_remove_points(message: Message):
    if not _is_admin(message.from_user.id):
        return

    parts = message.text.split(maxsplit=2)
    if len(parts) != 3 or not parts[2].lstrip("-").isdigit():
        await message.answer("Usage: /remove {username_or_id} {amount}")
        return

    identifier, amount = parts[1], int(parts[2])
    user_data = db.get_user(identifier)
    if not user_data:
        await message.answer(f"❌ User '{identifier}' not found.")
        return

    current = user_data.get("points", 0)
    new_bal = max(0, current - amount)
    db.set_points_direct(user_data["user_id"], new_bal)
    await message.answer(
        f"✅ Removed <b>{amount}</b> points from @{user_data.get('username') or user_data['user_id']}.\n"
        f"New balance: <b>{new_bal}</b>",
        parse_mode="HTML",
    )


@router.message(Command("check"))
async def admin_check_user(message: Message):
    if not _is_admin(message.from_user.id):
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) != 2:
        await message.answer("Usage: /check {username_or_id}")
        return

    user_data = db.get_user(parts[1])
    if not user_data:
        await message.answer(f"❌ User '{parts[1]}' not found.")
        return

    await message.answer(
        f"👤 <b>User Info</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🆔 ID: <code>{user_data['user_id']}</code>\n"
        f"👤 Username: @{user_data.get('username') or 'N/A'}\n"
        f"📛 Name: {user_data.get('full_name') or 'N/A'}\n"
        f"💰 Points: <b>{user_data.get('points', 0)}</b>\n"
        f"🎙 Generations: <b>{user_data.get('total_generations', 0)}</b>\n"
        f"🔒 Banned: {'Yes 🚫' if user_data.get('is_banned') else 'No ✅'}\n"
        f"📅 Joined: {user_data.get('created_at', 'N/A')}",
        parse_mode="HTML",
    )


@router.message(Command("msg"))
async def admin_msg_user(message: Message):
    if not _is_admin(message.from_user.id):
        return

    parts = message.text.split(maxsplit=2)
    if len(parts) != 3:
        await message.answer("Usage: /msg {username_or_id} {message}")
        return

    identifier, text = parts[1], parts[2]
    user_data = db.get_user(identifier)
    if not user_data:
        await message.answer(f"❌ User '{identifier}' not found.")
        return

    try:
        await bot.send_message(
            user_data["user_id"],
            f"📩 <b>Message from Admin:</b>\n\n{text}",
            parse_mode="HTML",
        )
        await message.answer("✅ Message sent.")
    except TelegramForbiddenError:
        await message.answer("❌ Could not send message — user may have blocked the bot.")


@router.message(Command("broadcast"))
async def admin_broadcast(message: Message):
    if not _is_admin(message.from_user.id):
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) != 2:
        await message.answer("Usage: /broadcast {message}")
        return

    text = parts[1]
    from firebase_admin import firestore as _fs

    users_stream = db.db.collection(db.USERS_COL).stream()
    sent, failed = 0, 0

    for doc in users_stream:
        u = doc.to_dict()
        if u.get("is_banned"):
            continue
        try:
            await bot.send_message(
                u["user_id"],
                f"📢 <b>Broadcast:</b>\n\n{text}",
                parse_mode="HTML",
            )
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)  # Respect Telegram rate limits

    await message.answer(f"✅ Broadcast complete.\n✔️ Sent: {sent} | ❌ Failed: {failed}")


@router.message(Command("ban"))
async def admin_ban(message: Message):
    if not _is_admin(message.from_user.id):
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) != 2:
        await message.answer("Usage: /ban {username_or_id}")
        return

    user_data = db.get_user(parts[1])
    if not user_data:
        await message.answer(f"❌ User '{parts[1]}' not found.")
        return

    db.ban_user(user_data["user_id"])
    await message.answer(
        f"🚫 User @{user_data.get('username') or user_data['user_id']} has been banned."
    )


@router.message(Command("unban"))
async def admin_unban(message: Message):
    if not _is_admin(message.from_user.id):
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) != 2:
        await message.answer("Usage: /unban {username_or_id}")
        return

    user_data = db.get_user(parts[1])
    if not user_data:
        await message.answer(f"❌ User '{parts[1]}' not found.")
        return

    db.unban_user(user_data["user_id"])
    await message.answer(
        f"✅ User @{user_data.get('username') or user_data['user_id']} has been unbanned."
    )


# ─────────────────────────────────────────────
# Entry Point
# ─────────────────────────────────────────────

async def main():
    logger.info("Bot is starting...")
    await dp.start_polling(bot, skip_updates=True)


if __name__ == "__main__":
    asyncio.run(main())
