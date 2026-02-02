import os
import random
import math
import asyncio
import aiosqlite
from aiogram import Bot, Dispatcher, executor, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup

API_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not API_TOKEN:
    raise ValueError("❌ TELEGRAM_BOT_TOKEN не задан!")

bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

class GameStates(StatesGroup):
    waiting_for_nickname = State()
    waiting_for_training_choice = State()
    in_game = State()
    in_menu = State()

# --- База данных ---
async def init_db():
    async with aiosqlite.connect("game.db") as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                nickname TEXT NOT NULL,
                wins INTEGER DEFAULT 0,
                xp INTEGER DEFAULT 0,
                completed_training BOOLEAN DEFAULT 0
            )
        """)
        await db.commit()

async def get_user(user_id):
    async with aiosqlite.connect("game.db") as db:
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cursor:
            return await cursor.fetchone()

async def create_user(user_id, nickname):
    async with aiosqlite.connect("game.db") as db:
        await db.execute(
            "INSERT INTO users (user_id, nickname, wins, xp, completed_training) VALUES (?, ?, 0, 0, 0)",
            (user_id, nickname)
        )
        await db.commit()

async def update_user_stats(user_id, wins_inc=0, xp_inc=0):
    async with aiosqlite.connect("game.db") as db:
        await db.execute(
            "UPDATE users SET wins = wins + ?, xp = xp + ? WHERE user_id = ?",
            (wins_inc, xp_inc, user_id)
        )
        await db.commit()

async def mark_training_completed(user_id):
    async with aiosqlite.connect("game.db") as db:
        await db.execute("UPDATE users SET completed_training = 1 WHERE user_id = ?", (user_id,))
        await db.commit()

async def get_top_user():
    async with aiosqlite.connect("game.db") as db:
        async with db.execute("""
            SELECT nickname, wins, xp FROM users ORDER BY wins DESC, xp DESC LIMIT 1
        """) as cursor:
            return await cursor.fetchone()

def generate_hint(secret):
    hints = []
    if secret % 2 == 0:
        hints.append("Это число чётное.")
    else:
        hints.append("Это число нечётное.")
    if secret % 5 == 0:
        hints.append("Это число делится на 5.")
    if secret % 3 == 0:
        hints.append("Это число делится на 3.")
    if secret > 500:
        hints.append("Число больше 500.")
    elif secret < 500:
        hints.append("Число меньше 500.")
    else:
        hints.append("Число равно 500!")
    return random.choice(hints)

def main_menu():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(types.KeyboardButton("👤 Профиль"), types.KeyboardButton("🎮 Играть"))
    keyboard.add(types.KeyboardButton("🏆 Рейтинг"))
    return keyboard

# --- Хендлеры ---
@dp.message_handler(commands=["start"])
async def cmd_start(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    user = await get_user(user_id)
    if user is None:
        await message.answer("Привет! Введи свой никнейм.\n⚠️ После ввода его нельзя будет изменить!")
        await GameStates.waiting_for_nickname.set()
    else:
        nickname, wins, xp, _ = user[1], user[2], user[3], user[4]
        await message.answer(f"Привет, {nickname}! Добро пожаловать в Скорованка!", reply_markup=main_menu())
        await GameStates.in_menu.set()

@dp.message_handler(state=GameStates.waiting_for_nickname)
async def process_nickname(message: types.Message, state: FSMContext):
    nickname = message.text.strip()
    if not nickname:
        await message.answer("Никнейм не может быть пустым. Попробуй снова:")
        return
    await create_user(message.from_user.id, nickname)
    await message.answer(f"Привет, {nickname}! Добро пожаловать в Скорованка!\nХотите пройти обучение? (да/нет)")
    await GameStates.waiting_for_training_choice.set()

@dp.message_handler(state=GameStates.waiting_for_training_choice)
async def process_training_choice(message: types.Message, state: FSMContext):
    text = message.text.strip().lower()
    if text in ["да", "yes", "д"]:
        await mark_training_completed(message.from_user.id)
        secret = random.randint(1, 1000)
        await state.update_data(secret_number=secret, attempts=0)
        hint = generate_hint(secret)
        await message.answer(
            "Я загадал число от 1 до 1000. Твоя задача — угадать его!\n"
            "Ты пишешь число, а я говорю: больше или меньше.\n"
            "Играем, пока ты не угадаешь 🙂\n\n"
            f"💡 Подсказка для новичка: {hint}\n\n"
            "Введи своё первое число:"
        )
        await GameStates.in_game.set()
    elif text in ["нет", "no", "н"]:
        await mark_training_completed(message.from_user.id)
        await message.answer("Хорошо! Удачи в игре!", reply_markup=main_menu())
        await GameStates.in_menu.set()
    else:
        await message.answer("Пожалуйста, напиши 'да' или 'нет'.")

@dp.message_handler(lambda message: message.text == "🎮 Играть", state=GameStates.in_menu)
async def start_game(message: types.Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    if not user:
        await message.answer("Сначала зарегистрируйся через /start")
        return
    secret = random.randint(1, 1000)
    await state.update_data(secret_number=secret, attempts=0)
    await message.answer("Я загадал число от 1 до 1000. Попробуй угадать!")
    await GameStates.in_game.set()

@dp.message_handler(state=GameStates.in_game)
async def handle_guess(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    secret = user_data["secret_number"]
    attempts = user_data.get("attempts", 0)

    try:
        guess = int(message.text.strip())
    except ValueError:
        await message.answer("Пожалуйста, введите целое число от 1 до 1000.")
        return

    if guess < 1 or guess > 1000:
        await message.answer("Число должно быть от 1 до 1000.")
        return

    attempts += 1
    await state.update_data(attempts=attempts)

    if guess == secret:
        max_xp = 100
        xp = max(1, int(max_xp / math.log(attempts + 1)))
        await update_user_stats(message.from_user.id, wins_inc=1, xp_inc=xp)
        await message.answer(
            f"🎉 Поздравляю! Ты угадал число {secret} за {attempts} попыток!\n"
            f"Ты получил {xp} XP!\n\n"
            "Напиши /start, чтобы открыть меню!"
        )
        await state.finish()
    else:
        user = await get_user(message.from_user.id)
        current_xp = user[3] if user else 0
        response = "Меньше." if guess > secret else "Больше."

        if current_xp < 1000 and attempts % 3 == 0:
            hint = generate_hint(secret)
            response += f"\n💡 Подсказка: {hint}"

        await message.answer(response)

@dp.message_handler(lambda message: message.text == "👤 Профиль", state=GameStates.in_menu)
async def show_profile(message: types.Message):
    user = await get_user(message.from_user.id)
    if not user:
        await message.answer("Сначала зарегистрируйся через /start")
        return
    user_id, nickname, wins, xp, _ = user
    await message.answer(
        f"👤 Профиль:\n"
        f"ID: {user_id}\n"
        f"Ник: {nickname}\n"
        f"Побед: {wins}\n"
        f"XP: {xp}"
    )

@dp.message_handler(lambda message: message.text == "🏆 Рейтинг", state=GameStates.in_menu)
async def show_rating(message: types.Message):
    top = await get_top_user()
    if top:
        nickname, wins, xp = top
        await message.answer(
            f"🏆 ТОП-1 игрок:\n"
            f"Ник: {nickname}\n"
            f"Побед: {wins}\n"
            f"XP: {xp}"
        )
    else:
        await message.answer("Рейтинг пока пуст.")

@dp.message_handler(state=GameStates.in_menu)
async def menu_handler(message: types.Message):
    if message.text == "👤 Профиль":
        await show_profile(message)
    elif message.text == "🎮 Играть":
        await start_game(message, dp.current_state(user=message.from_user.id))
    elif message.text == "🏆 Рейтинг":
        await show_rating(message)
    else:
        await message.answer("Используй кнопки меню.", reply_markup=main_menu())

# --- Запуск ---
if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(init_db())
    executor.start_polling(dp, skip_updates=True)
