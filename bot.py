import os
import random
import math
import aiosqlite
from aiogram import Bot, Dispatcher, types
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import Command, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
import asyncio

# Получаем токен из переменной окружения
API_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not API_TOKEN:
    raise ValueError("❌ Переменная окружения TELEGRAM_BOT_TOKEN не задана!")

bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Состояния
class GameStates(StatesGroup):
    waiting_for_nickname = State()
    waiting_for_training_choice = State()
    in_game = State()
    in_menu = State()

# Инициализация базы данных
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

# Получить пользователя
async def get_user(user_id: int):
    async with aiosqlite.connect("game.db") as db:
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cursor:
            return await cursor.fetchone()

# Создать пользователя
async def create_user(user_id: int, nickname: str):
    async with aiosqlite.connect("game.db") as db:
        await db.execute(
            "INSERT INTO users (user_id, nickname, wins, xp, completed_training) VALUES (?, ?, 0, 0, 0)",
            (user_id, nickname)
        )
        await db.commit()

# Обновить XP и победы
async def update_user_stats(user_id: int, wins_inc: int = 0, xp_inc: int = 0):
    async with aiosqlite.connect("game.db") as db:
        await db.execute(
            "UPDATE users SET wins = wins + ?, xp = xp + ? WHERE user_id = ?",
            (wins_inc, xp_inc, user_id)
        )
        await db.commit()

# Завершить обучение
async def mark_training_completed(user_id: int):
    async with aiosqlite.connect("game.db") as db:
        await db.execute("UPDATE users SET completed_training = 1 WHERE user_id = ?", (user_id,))
        await db.commit()

# Получить топ-1 игрока
async def get_top_user():
    async with aiosqlite.connect("game.db") as db:
        async with db.execute("""
            SELECT nickname, wins, xp FROM users ORDER BY wins DESC, xp DESC LIMIT 1
        """) as cursor:
            return await cursor.fetchone()

# Генерация подсказки для новичков
def generate_hint(secret: int) -> str:
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

# Главное меню
def main_menu() -> ReplyKeyboardMarkup:
    kb = [
        [KeyboardButton(text="👤 Профиль"), KeyboardButton(text="🎮 Играть")],
        [KeyboardButton(text="🏆 Рейтинг")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    user_id = message.from_user.id
    user = await get_user(user_id)

    if user is None:
        await message.answer(
            "Привет! Введи свой никнейм.\n⚠️ После ввода его нельзя будет изменить!"
        )
        await state.set_state(GameStates.waiting_for_nickname)
    else:
        nickname, wins, xp, completed_training = user[1], user[2], user[3], user[4]
        await message.answer(
            f"Привет, {nickname}! Добро пожаловать в Скорованка!",
            reply_markup=main_menu()
        )
        await state.set_state(GameStates.in_menu)

@dp.message(GameStates.waiting_for_nickname)
async def process_nickname(message: Message, state: FSMContext):
    nickname = message.text.strip()
    if not nickname:
        await message.answer("Никнейм не может быть пустым. Попробуй снова:")
        return
    await create_user(message.from_user.id, nickname)
    await message.answer(
        f"Привет, {nickname}! Добро пожаловать в Скорованка!\nХотите пройти обучение? (да/нет)"
    )
    await state.set_state(GameStates.waiting_for_training_choice)

@dp.message(GameStates.waiting_for_training_choice)
async def process_training_choice(message: Message, state: FSMContext):
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
        await state.set_state(GameStates.in_game)
    elif text in ["нет", "no", "н"]:
        await mark_training_completed(message.from_user.id)
        await message.answer("Хорошо! Удачи в игре!", reply_markup=main_menu())
        await state.set_state(GameStates.in_menu)
    else:
        await message.answer("Пожалуйста, напиши 'да' или 'нет'.")

@dp.message(F.text == "🎮 Играть")
async def start_game(message: Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    if not user:
        await message.answer("Сначала зарегистрируйся через /start")
        return

    secret = random.randint(1, 1000)
    await state.update_data(secret_number=secret, attempts=0)
    await message.answer("Я загадал число от 1 до 1000. Попробуй угадать!")
    await state.set_state(GameStates.in_game)

@dp.message(GameStates.in_game)
async def handle_guess(message: Message, state: FSMContext):
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
        await state.clear()
    else:
        user = await get_user(message.from_user.id)
        current_xp = user[3] if user else 0
        response = "Меньше." if guess > secret else "Больше."

        if current_xp < 1000 and attempts % 3 == 0:
            hint = generate_hint(secret)
            response += f"\n💡 Подсказка: {hint}"

        await message.answer(response)

@dp.message(F.text == "👤 Профиль")
async def show_profile(message: Message):
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

@dp.message(F.text == "🏆 Рейтинг")
async def show_rating(message: Message):
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

@dp.message(GameStates.in_menu)
async def menu_handler(message: Message):
    if message.text == "👤 Профиль":
        await show_profile(message)
    elif message.text == "🎮 Играть":
        await start_game(message, dp.fsm.get_context(message))
    elif message.text == "🏆 Рейтинг":
        await show_rating(message)
    else:
        await message.answer("Используй кнопки меню.", reply_markup=main_menu())

async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())