import asyncio
import sqlite3
import os
from datetime import datetime, timezone, timedelta
from contextlib import suppress
from typing import Callable, Awaitable, Any

from aiogram import Bot, Dispatcher, Router, F, BaseMiddleware
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, CallbackQuery, TelegramObject,
    InlineKeyboardMarkup, InlineKeyboardButton,
)
from aiogram.exceptions import TelegramBadRequest

from db import init_db, DB_PATH


# ============================================================
# КОНФИГУРАЦИЯ (из переменных окружения Bothost)
# ============================================================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "ВАШ_ТОКЕН_ДЛЯ_ЛОКАЛЬНОГО_ТЕСТА")
ACCESS_PASSWORD = os.environ.get("ACCESS_PASSWORD", "herewegoagain")

raw_admins = os.environ.get("CHIEF_ADMIN_IDS", "")
CHIEF_ADMIN_IDS = set()
if raw_admins:
    CHIEF_ADMIN_IDS = {int(i.strip()) for i in raw_admins.split(",") if i.strip().isdigit()}
else:
    CHIEF_ADMIN_IDS = {123456789} 

ADMIN_IDS = CHIEF_ADMIN_IDS

REMINDER_INTERVAL = 1800  # секунды (30 минут)

# Московский часовой пояс (UTC+3)
MSK = timezone(timedelta(hours=3))


def now_msk() -> datetime:
    return datetime.now(MSK)


def today_msk() -> str:
    return now_msk().strftime("%Y-%m-%d")


def ts_msk() -> str:
    return now_msk().strftime("%Y-%m-%d %H:%M:%S")


def is_chief_admin(user_id: int) -> bool:
    return user_id in CHIEF_ADMIN_IDS


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def get_db() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH)


def log_action(schedule_id, action, actor, details=""):
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO audit_log (schedule_id, action, actor, details, timestamp) "
            "VALUES (?, ?, ?, ?, ?)",
            (schedule_id, action, actor, details, ts_msk()),
        )
        conn.commit()
    finally:
        conn.close()


def is_authorized(user_id: int) -> bool:
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("SELECT 1 FROM auth_users WHERE tg_id = ?", (user_id,))
        return c.fetchone() is not None
    finally:
        conn.close()


def authorize_user(user_id: int, name: str):
    conn = get_db()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO auth_users (tg_id, name, authorized_at) VALUES (?, ?, ?)",
            (user_id, name, ts_msk()),
        )
        conn.commit()
    finally:
        conn.close()


# ============================================================
# ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ: КАЛЕНДАРЬ
# ============================================================
def get_dates_keyboard():
    """Генерирует кнопки с датами на 14 дней вперед"""
    keyboard = []
    today = now_msk().date()
    
    # Делаем по 2 даты в ряд
    row = []
    for i in range(14):
        d = today + timedelta(days=i)
        day_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
        label = f"{d.strftime('%d.%m')} ({day_names[d.weekday()]})"
        
        # callback_data передает дату в формате базы данных (YYYY-MM-DD)
        callback_data = f"date_pick:{d.strftime('%Y-%m-%d')}"
        
        row.append(InlineKeyboardButton(text=label, callback_data=callback_data))
        
        if len(row) == 2:
            keyboard.append(row)
            row = []
            
    if row:
        keyboard.append(row)
        
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


# ============================================================
# ИНИЦИАЛИЗАЦИЯ БОТА
# ============================================================
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)


# ============================================================
# MIDDLEWARE (Защита паролем)
# ============================================================
class AuthMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None:
            return await handler(event, data)

        if is_authorized(user.id):
            return await handler(event, data)

        text = getattr(event, "text", None) or ""
        if isinstance(text, str):
            if text.startswith("/start") or text == ACCESS_PASSWORD:
                return await handler(event, data)

        return None


dp.message.middleware(AuthMiddleware())
dp.callback_query.middleware(AuthMiddleware())


# ============================================================
# ВВОД ПАРОЛЯ
# ============================================================
@router.message(F.text == ACCESS_PASSWORD)
async def handle_password(message: Message):
    user_id = message.from_user.id
    if is_authorized(user_id):
        await message.answer("Вы уже авторизованы. Отправьте /start.")
        return

    name = message.from_user.full_name or str(user_id)
    authorize_user(user_id, name)
    log_action(0, "auth", name, "success")
    await message.answer(
        f"✅ Доступ открыт, {name}.\n\n"
        "Отправьте /start, чтобы увидеть меню."
    )


# ============================================================
# /start
# ============================================================
@router.message(Command("start"))
async def cmd_start(message: Message):
    user_id = message.from_user.id

    if not is_authorized(user_id):
        await message.answer(
            "🔒 Это внутренний бот конюшни.\n"
            "Введите пароль для доступа:"
        )
        return

    if is_chief_admin(user_id):
        text = (
            "🐴 **Панель главного администратора**\n\n"
            "/today — расписание на сегодня\n"
            "/schedule — всё расписание\n"
            "/add — добавить запись\n"
            "/edit — редактировать/удалить\n"
            "/trash — корзина удалённых записей\n"
            "/horses — список лошадей\n"
            "/addhorse — добавить лошадь\n"
            "/register — привязать имя к аккаунту\n"
            "/log — журнал действий\n"
            "/revoke — отозвать доступ у пользователя"
        )
    elif is_admin(user_id):
        text = (
            "🐴 **Панель администратора**\n\n"
            "/today — расписание на сегодня\n"
            "/schedule — всё расписание\n"
            "/add — добавить запись\n"
            "/edit — редактировать/удалить\n"
            "/horses — список лошадей\n"
            "/addhorse — добавить лошадь\n"
            "/register — привязать имя к аккаунту"
        )
    else:
        text = (
            "🐴 **Добро пожаловать**\n\n"
            "/today — расписание на сегодня\n"
            "/schedule — всё расписание\n"
            "/add — добавить запись\n"
            "/edit — редактировать расписание\n"
            "/horses — информация о лошадях\n"
            "/register — привязать имя к аккаунту"
        )

    await message.answer(text, parse_mode="Markdown")


# ============================================================
# /schedule
# ============================================================
@router.message(Command("schedule"))
async def cmd_schedule(message: Message):
    today = today_msk()
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("""
            SELECT date, time_slot, instructor, horse_name, task_type
            FROM schedule
            WHERE date >= ? AND deleted_at IS NULL
            ORDER BY date, time_slot
        """, (today,))
        rows = c.fetchall()
    finally:
        conn.close()

    if not rows:
        await message.answer("Ближайшее расписание пусто.")
        return

    lines = ["📅 **Расписание**\n"]
    current_date = None
    for date, time_slot, instructor, horse, task in rows:
        if date != current_date:
            lines.append(f"\n**{date}**")
            current_date = date
        lines.append(f"  {time_slot} | {instructor} | {horse} | {task}")

    text = "\n".join(lines)
    for chunk_start in range(0, len(text), 4000):
        await message.answer(
            text[chunk_start:chunk_start + 4000],
            parse_mode="Markdown",
        )


# ============================================================
# /today
# ============================================================
@router.message(Command("today"))
async def cmd_today(message: Message):
    today = today_msk()
    today_str = now_msk().strftime("%d.%m.%Y")

    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("""
            SELECT time_slot, instructor, horse_name, task_type
            FROM schedule
            WHERE date = ? AND deleted_at IS NULL
            ORDER BY time_slot
        """, (today,))
        rows = c.fetchall()
    finally:
        conn.close()

    if not rows:
        await message.answer(
            f"📅 **{today_str}**\n\nНа сегодня записей нет.",
            parse_mode="Markdown",
        )
        return

    by_instructor = {}
    for time_slot, instructor, horse, task in rows:
        by_instructor.setdefault(instructor, []).append((time_slot, horse, task))

    lines = [f"📅 **Сегодня, {today_str}**\n"]
    for instructor, items in by_instructor.items():
        lines.append(f"\n👤 **{instructor}**")
        for time_slot, horse, task in items:
            lines.append(f"  {time_slot} | {horse} | {task}")

    horse_counter = {}
    for _, horse, _ in rows:
        horse_counter[horse] = horse_counter.get(horse, 0) + 1

    lines.append("\n🐎 **Задействованные лошади**")
    for horse, count in sorted(horse_counter.items(), key=lambda x: -x[1]):
        lines.append(f"  {horse}: {count} раз(а)")

    text = "\n".join(lines)
    for chunk_start in range(0, len(text), 4000):
        await message.answer(
            text[chunk_start:chunk_start + 4000],
            parse_mode="Markdown",
        )


# ============================================================
# /add
# ============================================================
class AddSchedule(StatesGroup):
    waiting_date = State()
    waiting_time = State()
    waiting_instructor = State()
    waiting_horse = State()
    waiting_task = State()


@router.message(Command("add"))
async def cmd_add(message: Message, state: FSMContext):
    await state.set_state(AddSchedule.waiting_date)
    await message.answer(
        "Выберите дату из списка:", 
        reply_markup=get_dates_keyboard()
    )


@router.callback_query(F.data.startswith("date_pick:"), AddSchedule.waiting_date)
async def process_date_callback(callback: CallbackQuery, state: FSMContext):
    chosen_date = callback.data.split(":")[1]
    await state.update_data(date=chosen_date)
    await state.set_state(AddSchedule.waiting_time)
    
    await callback.message.edit_text(
        f"Выбрана дата: {chosen_date}\n\n"
        "Введите время (например 09:00-10:00):"
    )
    await callback.answer()


@router.message(AddSchedule.waiting_time)
async def process_time(message: Message, state: FSMContext):
    await state.update_data(time_slot=message.text.strip())
    await state.set_state(AddSchedule.waiting_instructor)
    await message.answer("Имя инструктора:")


@router.message(AddSchedule.waiting_instructor)
async def process_instructor(message: Message, state: FSMContext):
    await state.update_data(instructor=message.text.strip())
    await state.set_state(AddSchedule.waiting_horse)
    await message.answer("Кличка лошади:")


@router.message(AddSchedule.waiting_horse)
async def process_horse(message: Message, state: FSMContext):
    await state.update_data(horse_name=message.text.strip())
    await state.set_state(AddSchedule.waiting_task)
    await message.answer("Тип занятия (прокат/уход/тренировка):")


@router.message(AddSchedule.waiting_task)
async def process_task(message: Message, state: FSMContext):
    await state.update_data(task_type=message.text.strip())
    data = await state.get_data()

    user_id = message.from_user.id
    author_name = message.from_user.full_name or str(user_id)

    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("""
            SELECT id FROM schedule
            WHERE date=? AND time_slot=? AND deleted_at IS NULL
              AND (instructor=? OR horse_name=?)
        """, (data["date"], data["time_slot"], data["instructor"], data["horse_name"]))

        if c.fetchone():
            await message.answer(
                "⚠️ Конфликт: инструктор или лошадь уже заняты в это время.\n"
                "Отредактируйте существующую запись через /edit."
            )
            await state.clear()
            return

        c.execute("""
            INSERT INTO schedule
                (date, time_slot, instructor, horse_name, task_type,
                 created_by, created_by_name, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data["date"], data["time_slot"],
            data["instructor"], data["horse_name"], data["task_type"],
            str(user_id), author_name, ts_msk(),
        ))
        conn.commit()
        new_id = c.lastrowid
    finally:
        conn.close()

    log_action(new_id, "create", author_name, str(data))
    await message.answer(
        f"✅ Запись добавлена:\n"
        f"{data['date']} {data['time_slot']}\n"
        f"{data['instructor']} | {data['horse_name']} | {data['task_type']}"
    )
    await state.clear()


# ============================================================
# /edit
# ============================================================
@router.message(Command("edit"))
async def cmd_edit(message: Message):
    today = today_msk()
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("""
            SELECT id, date, time_slot, instructor, horse_name
            FROM schedule
            WHERE date >= ? AND deleted_at IS NULL
            ORDER BY date, time_slot
            LIMIT 20
        """, (today,))
        rows = c.fetchall()
    finally:
        conn.close()

    if not rows:
        await message.answer("Активных записей нет.")
        return

    buttons = []
    for row_id, date, time_slot, instructor, horse in rows:
        label = f"{date} {time_slot} | {instructor} | {horse}"
        buttons.append([InlineKeyboardButton(
            text=label[:60],
            callback_data=f"edit:{row_id}",
        )])

    await message.answer(
        "Выберите запись:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


# ============================================================
# Карточка записи
# ============================================================
@router.callback_query(F.data.startswith("edit:"))
async def show_card(callback: CallbackQuery):
    row_id = int(callback.data.split(":")[1])
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("""
            SELECT date, time_slot, instructor, horse_name, task_type,
                   created_by_name, updated_at
            FROM schedule WHERE id = ? AND deleted_at IS NULL
        """, (row_id,))
        row = c.fetchone()
    finally:
        conn.close()

    if not row:
        await callback.answer("Запись не найдена или уже удалена.")
        return

    text = (
        f"📝 **Запись #{row_id}**\n\n"
        f"Дата: {row[0]}\nВремя: {row[1]}\n"
        f"Инструктор: {row[2]}\nЛошадь: {row[3]}\n"
        f"Занятие: {row[4]}\nАвтор: {row[5] or '?'}"
    )
    if row[6]:
        text += f"\nИзменено: {row[6]} (МСК)"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✏️ Дата", callback_data=f"field:{row_id}:date"),
            InlineKeyboardButton(text="✏️ Время", callback_data=f"field:{row_id}:time_slot"),
        ],
        [
            InlineKeyboardButton(text="✏️ Инструктор", callback_data=f"field:{row_id}:instructor"),
            InlineKeyboardButton(text="✏️ Лошадь", callback_data=f"field:{row_id}:horse_name"),
        ],
        [
            InlineKeyboardButton(text="✏️ Занятие", callback_data=f"field:{row_id}:task_type"),
        ],
        [
            InlineKeyboardButton(text="🗑 Удалить", callback_data=f"softdel:{row_id}"),
        ],
    ])

    with suppress(TelegramBadRequest):
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")
    await callback.answer()


# ============================================================
# Изменение поля
# ============================================================
class EditField(StatesGroup):
    waiting_value = State()


ALLOWED_FIELDS = {"date", "time_slot", "instructor", "horse_name", "task_type"}


@router.callback_query(F.data.startswith("field:"))
async def start_edit(callback: CallbackQuery, state: FSMContext):
    _, row_id, field = callback.data.split(":")
    if field not in ALLOWED_FIELDS:
        await callback.answer("Недопустимое поле.", show_alert=True)
        return
    
    await state.update_data(row_id=int(row_id), field=field)
    await state.set_state(EditField.waiting_value)
    
    if field == "date":
        await callback.message.answer(
            "Выберите новую дату:", 
            reply_markup=get_dates_keyboard()
        )
    else:
        await callback.message.answer(f"Введите новое значение для поля «{field}»:")
    
    await callback.answer()


@router.callback_query(F.data.startswith("date_pick:"), EditField.waiting_value)
async def apply_date_edit(callback: CallbackQuery, state: FSMContext):
    new_date = callback.data.split(":")[1]
    data = await state.get_data()
    row_id = data["row_id"]
    field = data["field"]
    editor = callback.from_user.full_name or str(callback.from_user.id)

    conn = get_db()
    try:
        conn.execute(f"""
            UPDATE schedule SET {field} = ?, updated_at = ?, updated_by = ?
            WHERE id = ? AND deleted_at IS NULL
        """, (new_date, ts_msk(), editor, row_id))
        conn.commit()
    finally:
        conn.close()

    log_action(row_id, "update", editor, f"{field}={new_date}")
    await callback.message.edit_text(f"✅ Обновлено: {field} → {new_date}")
    await state.clear()
    await callback.answer()


@router.message(EditField.waiting_value)
async def apply_edit(message: Message, state: FSMContext):
    data = await state.get_data()
    row_id = data["row_id"]
    field = data["field"]
    new_value = message.text.strip()

    if field not in ALLOWED_FIELDS:
        await message.answer("Недопустимое поле.")
        await state.clear()
        return

    # Если вдруг ввели текст вместо кнопки для даты
    if field == "date":
        try:
            parsed = datetime.strptime(new_value, "%Y-%m-%d").date()
        except ValueError:
            await message.answer("Неверный формат. ГГГГ-ММ-ДД:")
            return
        if parsed < now_msk().date():
            await message.answer("Дата уже прошла. Введите сегодняшнюю или будущую дату:")
            return

    editor = message.from_user.full_name or str(message.from_user.id)
    conn = get_db()
    try:
        conn.execute(f"""
            UPDATE schedule SET {field} = ?, updated_at = ?, updated_by = ?
            WHERE id = ? AND deleted_at IS NULL
        """, (new_value, ts_msk(), editor, row_id))
        conn.commit()
    finally:
        conn.close()

    log_action(row_id, "update", editor, f"{field}={new_value}")
    await message.answer(f"✅ Обновлено: {field} → {new_value}")
    await state.clear()


# ============================================================
# Мягкое удаление
# ============================================================
@router.callback_query(F.data.startswith("softdel:"))
async def confirm_softdel(callback: CallbackQuery):
    row_id = int(callback.data.split(":")[1])
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Удалить", callback_data=f"softdelconf:{row_id}"),
            InlineKeyboardButton(text="❌ Отмена", callback_data=f"edit:{row_id}"),
        ]
    ])
    with suppress(TelegramBadRequest):
        await callback.message.edit_text(
            f"Удалить запись #{row_id}? Она переместится в корзину.",
            reply_markup=keyboard,
        )
    await callback.answer()


@router.callback_query(F.data.startswith("softdelconf:"))
async def do_softdel(callback: CallbackQuery):
    row_id = int(callback.data.split(":")[1])
    actor = callback.from_user.full_name or str(callback.from_user.id)

    conn = get_db()
    try:
        conn.execute("""
            UPDATE schedule SET deleted_at = ?, deleted_by = ?
            WHERE id = ? AND deleted_at IS NULL
        """, (ts_msk(), actor, row_id))
        conn.commit()
    finally:
        conn.close()

    log_action(row_id, "soft_delete", actor)
    with suppress(TelegramBadRequest):
        await callback.message.edit_text(f"🗑 Запись #{row_id} перемещена в корзину.")
    await callback.answer()


# ============================================================
# /trash
# ============================================================
@router.message(Command("trash"))
async def cmd_trash(message: Message):
    if not is_chief_admin(message.from_user.id):
        await message.answer("⛔ Только главный администратор может просматривать корзину.")
        return

    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("""
            SELECT id, date, time_slot, instructor, horse_name, deleted_by, deleted_at
            FROM schedule
            WHERE deleted_at IS NOT NULL
            ORDER BY deleted_at DESC
            LIMIT 20
        """)
        rows = c.fetchall()
    finally:
        conn.close()

    if not rows:
        await message.answer("Корзина пуста.")
        return

    buttons = []
    for row_id, date, time_slot, instructor, horse, deleted_by, deleted_at in rows:
        label = f"#{row_id} {date} {time_slot} | {instructor}"
        buttons.append([InlineKeyboardButton(
            text=label[:60],
            callback_data=f"restore:{row_id}",
        )])

    await message.answer(
        "🗑 **Удалённые записи** (нажмите для восстановления):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="Markdown",
    )


# ============================================================
# Восстановление
# ============================================================
@router.callback_query(F.data.startswith("restore:"))
async def do_restore(callback: CallbackQuery):
    if not is_chief_admin(callback.from_user.id):
        await callback.answer("⛔ Нет прав.", show_alert=True)
        return

    row_id = int(callback.data.split(":")[1])
    actor = callback.from_user.full_name or str(callback.from_user.id)

    conn = get_db()
    try:
        c = conn.cursor()
        c.execute(
            "SELECT date, time_slot, instructor, horse_name FROM schedule WHERE id=?",
            (row_id,),
        )
        row = c.fetchone()
        if not row:
            await callback.answer("Запись не найдена.", show_alert=True)
            return

        c.execute("""
            SELECT id FROM schedule
            WHERE date=? AND time_slot=? AND (instructor=? OR horse_name=?)
              AND deleted_at IS NULL
        """, (row[0], row[1], row[2], row[3]))
        if c.fetchone():
            await callback.answer(
                "⚠️ Нельзя восстановить: на это время уже есть активная запись.",
                show_alert=True,
            )
            return

        conn.execute("""
            UPDATE schedule SET deleted_at = NULL, deleted_by = NULL
            WHERE id = ? AND deleted_at IS NOT NULL
        """, (row_id,))
        conn.commit()
    finally:
        conn.close()

    log_action(row_id, "restore", actor)
    with suppress(TelegramBadRequest):
        await callback.message.edit_text(f"✅ Запись #{row_id} восстановлена.")
    await callback.answer()


# ============================================================
# /horses
# ============================================================
@router.message(Command("horses"))
async def cmd_horses(message: Message):
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("SELECT name, status, care_notes FROM horses ORDER BY name")
        rows = c.fetchall()
    finally:
        conn.close()

    if not rows:
        await message.answer("Информация о лошадях пока не добавлена.")
        return

    lines = ["🐎 **Список лошадей**\n"]
    for name, status, notes in rows:
        lines.append(f"**{name}** | {status}")
        if notes:
            lines.append(f"  _{notes}_")

    text = "\n".join(lines)
    for chunk_start in range(0, len(text), 4000):
        await message.answer(
            text[chunk_start:chunk_start + 4000],
            parse_mode="Markdown",
        )


# ============================================================
# /addhorse
# ============================================================
class AddHorse(StatesGroup):
    waiting_name = State()
    waiting_status = State()
    waiting_notes = State()


@router.message(Command("addhorse"))
async def cmd_addhorse(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Только администраторы могут добавлять лошадей.")
        return
    await state.set_state(AddHorse.waiting_name)
    await message.answer("Кличка лошади:")


@router.message(AddHorse.waiting_name)
async def horse_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await state.set_state(AddHorse.waiting_status)
    await message.answer("Статус (доступна/отдыхает/болеет):")


@router.message(AddHorse.waiting_status)
async def horse_status(message: Message, state: FSMContext):
    await state.update_data(status=message.text.strip())
    await state.set_state(AddHorse.waiting_notes)
    await message.answer("Заметки по уходу (или «-», чтобы пропустить):")


@router.message(AddHorse.waiting_notes)
async def horse_notes(message: Message, state: FSMContext):
    notes = message.text.strip()
    if notes == "-":
        notes = ""
    await state.update_data(notes=notes)
    data = await state.get_data()

    conn = get_db()
    try:
        conn.execute("""
            INSERT OR REPLACE INTO horses (name, status, care_notes)
            VALUES (?, ?, ?)
        """, (data["name"], data["status"], notes))
        conn.commit()
    finally:
        conn.close()

    await message.answer(f"✅ Лошадь «{data['name']}» сохранена.")
    await state.clear()


# ============================================================
# /register
# ============================================================
class Register(StatesGroup):
    waiting_name = State()


@router.message(Command("register"))
async def cmd_register(message: Message, state: FSMContext):
    await state.set_state(Register.waiting_name)
    await message.answer("Введите ваше имя так, как оно указано в расписании:")


@router.message(Register.waiting_name)
async def process_register(message: Message, state: FSMContext):
    name = message.text.strip()
    conn = get_db()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO employees (tg_id, name) VALUES (?, ?)",
            (message.from_user.id, name),
        )
        conn.commit()
    finally:
        conn.close()

    await message.answer(f"✅ Имя «{name}» привязано. Вы будете получать напоминания.")
    await state.clear()


# ============================================================
# /log
# ============================================================
@router.message(Command("log"))
async def cmd_log(message: Message):
    if not is_chief_admin(message.from_user.id):
        await message.answer("⛔ Команда доступна только главному администратору.")
        return

    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("""
            SELECT timestamp, action, schedule_id, actor, details
            FROM audit_log
            ORDER BY id DESC
            LIMIT 30
        """)
        rows = c.fetchall()
    finally:
        conn.close()

    if not rows:
        await message.answer("Журнал пуст.")
        return

    emoji = {
        "create": "➕", "update": "✏️", "soft_delete": "🗑",
        "restore": "♻️", "auth": "🔑", "revoke": "🚫",
    }

    lines = ["📋 **Последние действия (МСК)**\n"]
    for ts, action, sid, actor, details in rows:
        e = emoji.get(action, "•")
        lines.append(f"{e} {ts} | #{sid} | {actor or '?'} | {action}")

    text = "\n".join(lines)
    for chunk_start in range(0, len(text), 4000):
        await message.answer(
            text[chunk_start:chunk_start + 4000],
            parse_mode="Markdown",
        )


# ============================================================
# /revoke
# ============================================================
@router.message(Command("revoke"))
async def cmd_revoke(message: Message):
    if not is_chief_admin(message.from_user.id):
        await message.answer("⛔ Только главный администратор может отзывать доступ.")
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip().isdigit():
        await message.answer("Использование: /revoke <tg_id>")
        return

    target_id = int(parts[1].strip())
    if target_id in CHIEF_ADMIN_IDS:
        await message.answer("⛔ Нельзя отозвать доступ у главного администратора.")
        return

    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("DELETE FROM auth_users WHERE tg_id = ?", (target_id,))
        deleted = c.rowcount
        conn.commit()
    finally:
        conn.close()

    if deleted:
        await message.answer(f"✅ Доступ пользователя {target_id} отозван.")
        log_action(0, "revoke", message.from_user.full_name, f"tg_id={target_id}")
    else:
        await message.answer(f"Пользователь {target_id} не найден среди авторизованных.")


# ============================================================
# Фоновые напоминания (по Москве)
# ============================================================
async def reminder_loop():
    while True:
        try:
            await asyncio.sleep(REMINDER_INTERVAL)

            target = now_msk() + timedelta(hours=1)
            target_date = target.strftime("%Y-%m-%d")
            target_prefix = target.strftime("%H:")

            conn = get_db()
            try:
                c = conn.cursor()
                c.execute("""
                    SELECT s.time_slot, s.instructor, s.horse_name, s.task_type, e.tg_id
                    FROM schedule s
                    JOIN employees e ON s.instructor = e.name
                    WHERE s.deleted_at IS NULL
                      AND s.date = ?
                      AND s.time_slot LIKE ?
                """, (target_date, target_prefix + "%"))
                rows = c.fetchall()
            finally:
                conn.close()

            for time_slot, instructor, horse, task, tg_id in rows:
                with suppress(Exception):
                    await bot.send_message(
                        tg_id,
                        f"⏰ Напоминание: через час ({time_slot}) "
                        f"у вас {task} — лошадь {horse}.",
                    )
        except Exception as e:
            print(f"[reminder_loop] error: {e}")


# ============================================================
# ТОЧКА ВХОДА
# ============================================================
async def main():
    init_db()
    asyncio.create_task(reminder_loop())
    print("Бот запущен. Часовой пояс: МСК (UTC+3).")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())