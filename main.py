import asyncio
import sqlite3
import os
from datetime import datetime, timezone, timedelta
from contextlib import suppress

from aiogram import Bot, Dispatcher, Router, F, BaseMiddleware
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, CallbackQuery, 
    InlineKeyboardMarkup, InlineKeyboardButton,
)
from aiogram.exceptions import TelegramBadRequest

from db import init_db, DB_PATH

# ============================================================
# КОНФИГУРАЦИЯ
# ============================================================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "ВАШ_ТОКЕН")
ACCESS_PASSWORD = os.environ.get("ACCESS_PASSWORD", "herewegoagain")

raw_admins = os.environ.get("CHIEF_ADMIN_IDS", "")
CHIEF_ADMIN_IDS = set()
if raw_admins:
    CHIEF_ADMIN_IDS = {int(i.strip()) for i in raw_admins.split(",") if i.strip().isdigit()}
else:
    CHIEF_ADMIN_IDS = {123456789} 

ADMIN_IDS = CHIEF_ADMIN_IDS
REMINDER_INTERVAL = 1800
MSK = timezone(timedelta(hours=3))

def now_msk() -> datetime: return datetime.now(MSK)
def today_msk() -> str: return now_msk().strftime("%Y-%m-%d")
def ts_msk() -> str: return now_msk().strftime("%Y-%m-%d %H:%M:%S")
def is_chief_admin(user_id: int) -> bool: return user_id in CHIEF_ADMIN_IDS

def get_db() -> sqlite3.Connection: return sqlite3.connect(DB_PATH)

def log_action(schedule_id, action, actor, details=""):
    conn = get_db()
    try:
        conn.execute("INSERT INTO audit_log (schedule_id, action, actor, details, timestamp) VALUES (?, ?, ?, ?, ?)",
                     (schedule_id, action, actor, details, ts_msk()))
        conn.commit()
    finally: conn.close()

def is_authorized(user_id: int) -> bool:
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("SELECT 1 FROM auth_users WHERE tg_id = ?", (user_id,))
        return c.fetchone() is not None
    finally: conn.close()

def authorize_user(user_id: int, name: str):
    conn = get_db()
    try:
        conn.execute("INSERT OR REPLACE INTO auth_users (tg_id, name, authorized_at) VALUES (?, ?, ?)", (user_id, name, ts_msk()))
        conn.commit()
    finally: conn.close()

# ============================================================
# КЛАВИАТУРЫ
# ============================================================
def get_dates_keyboard():
    keyboard, row = [], []
    today = now_msk().date()
    for i in range(14):
        d = today + timedelta(days=i)
        day_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
        label = f"{d.strftime('%d.%m')} ({day_names[d.weekday()]})"
        row.append(InlineKeyboardButton(text=label, callback_data=f"date_pick:{d.strftime('%Y-%m-%d')}"))
        if len(row) == 2:
            keyboard.append(row); row = []
    if row: keyboard.append(row)
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_times_keyboard():
    keyboard, row = [], []
    for hour in range(8, 21):
        row.append(InlineKeyboardButton(text=f"{hour:02d}:00", callback_data=f"time_pick:{hour:02d}:00"))
        if len(row) == 4:
            keyboard.append(row); row = []
    if row: keyboard.append(row)
    keyboard.append([InlineKeyboardButton(text="⬅️ Назад к датам", callback_data="back_to_dates")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_main_type_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏇 Прокат", callback_data="main_type:rental")],
        [InlineKeyboardButton(text="🐎 Поручение по лошади", callback_data="main_type:task")]
    ])

def get_rental_type_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🐎 Прогулка", callback_data="type_pick:Прогулка"), InlineKeyboardButton(text="📸 Фотосессия", callback_data="type_pick:Фотосессия")],
        [InlineKeyboardButton(text="🏇 Тренировка", callback_data="type_pick:Тренировка")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main_type")]
    ])

def get_durations_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="30 минут", callback_data="dur_pick:30 минут"), InlineKeyboardButton(text="45 минут", callback_data="dur_pick:45 минут")],
        [InlineKeyboardButton(text="1 час", callback_data="dur_pick:1 час")],
        [InlineKeyboardButton(text="⬅️ Назад к типу", callback_data="back_to_types")]
    ])

def get_instructors_count_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1", callback_data="instr_count:1"), InlineKeyboardButton(text="2", callback_data="instr_count:2"), InlineKeyboardButton(text="3", callback_data="instr_count:3")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_durs")]
    ])

# ============================================================
# БОТ И MIDDLEWARE
# ============================================================
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

class AuthMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        if user is None: return await handler(event, data)
        if is_authorized(user.id): return await handler(event, data)
        text = getattr(event, "text", None) or ""
        if text.startswith("/start") or text == ACCESS_PASSWORD: return await handler(event, data)
        return None

dp.message.middleware(AuthMiddleware())
dp.callback_query.middleware(AuthMiddleware())

# ============================================================
# СТАРТ
# ============================================================
@router.message(F.text == ACCESS_PASSWORD)
async def handle_password(message: Message):
    if is_authorized(message.from_user.id): return await message.answer("Вы уже авторизованы.")
    name = message.from_user.full_name or str(message.from_user.id)
    authorize_user(message.from_user.id, name)
    await message.answer(f"✅ Доступ открыт, {name}.\nОтправьте /start")

@router.message(Command("start"))
async def cmd_start(message: Message):
    if not is_authorized(message.from_user.id): return await message.answer("🔒 Введите пароль:")
    text = "🐴 <b>Панель управления</b>\n\n/today — на сегодня\n/schedule — все записи\n/add — создать запись\n/edit — редактировать/удалить\n/register — привязать имя"
    if is_chief_admin(message.from_user.id): text += "\n/log — журнал действий\n/revoke — отозвать доступ"
    await message.answer(text, parse_mode="HTML")

# ============================================================
# /schedule И /today
# ============================================================
@router.message(Command("schedule"))
async def cmd_schedule(message: Message):
    today = today_msk()
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("SELECT id, record_type, date, time_slot, task_type, duration, horse_name, required_instructors, assigned_instructors FROM schedule WHERE date >= ? AND deleted_at IS NULL ORDER BY date, time_slot", (today,))
        rows = c.fetchall()
    finally: conn.close()

    if not rows: return await message.answer("Расписание пусто.")
    by_date = {}
    for r in rows: by_date.setdefault(r[2], []).append(r)
    lines, day_names = [], ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    for date, items in by_date.items():
        d_obj = datetime.strptime(date, "%Y-%m-%d")
        lines.append(f"📅 <b>{d_obj.strftime('%d.%m')} ({day_names[d_obj.weekday()]})</b>")
        for r in items:
            _, r_type, _, time_slot, task, dur, horse, req, assigned = r
            assigned_text = assigned if assigned else "❌"
            if r_type == 'rental':
                lines.append(f"  🏇 {time_slot} | {task} ({dur})\n     👤 Нужно: {req} | Взяли: {assigned_text}")
            else:
                lines.append(f"  🐎 {time_slot} | {horse}: {task}\n     👤 Сделает: {assigned_text}")
        lines.append("")
    text = "\n".join(lines)
    for i in range(0, len(text), 4000): await message.answer(text[i:i+4000], parse_mode="HTML")

@router.message(Command("today"))
async def cmd_today(message: Message):
    today = today_msk()
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("SELECT record_type, time_slot, task_type, duration, horse_name, required_instructors, assigned_instructors FROM schedule WHERE date = ? AND deleted_at IS NULL ORDER BY time_slot", (today,))
        rows = c.fetchall()
    finally: conn.close()
    if not rows: return await message.answer(f"📅 <b>{now_msk().strftime('%d.%m.%Y')}</b>\nЗаписей нет.", parse_mode="HTML")
    
    lines = [f"📅 <b>Сегодня, {now_msk().strftime('%d.%m.%Y')}</b>\n"]
    for r in rows:
        r_type, time_slot, task, dur, horse, req, assigned = r
        assigned_text = assigned if assigned else "❌"
        if r_type == 'rental': lines.append(f"🏇 {time_slot} | {task} ({dur})\n👤 Нужно: {req} | Взяли: {assigned_text}\n")
        else: lines.append(f"🐎 {time_slot} | {horse}: {task}\n👤 Сделает: {assigned_text}\n")
    text = "\n".join(lines)
    for i in range(0, len(text), 4000): await message.answer(text[i:i+4000], parse_mode="HTML")

# ============================================================
# /add (СОЗДАНИЕ)
# ============================================================
class AddSchedule(StatesGroup):
    waiting_main_type = State()
    waiting_date = State()
    waiting_time = State()
    waiting_rental_type = State()
    waiting_duration = State()
    waiting_instr_count = State()
    waiting_task_horse = State()
    waiting_task_desc = State()

@router.message(Command("add"))
async def cmd_add(message: Message, state: FSMContext):
    await state.set_state(AddSchedule.waiting_main_type)
    await message.answer("Что создаем?", reply_markup=get_main_type_keyboard())

@router.callback_query(F.data.startswith("main_type:"), AddSchedule.waiting_main_type)
async def process_main_type(callback: CallbackQuery, state: FSMContext):
    m_type = callback.data.split(":")[1]
    await state.update_data(record_type=m_type)
    await state.set_state(AddSchedule.waiting_date)
    await callback.message.edit_text("Выберите дату:", reply_markup=get_dates_keyboard())
    await callback.answer()

@router.callback_query(F.data.startswith("date_pick:"), AddSchedule.waiting_date)
async def process_date(callback: CallbackQuery, state: FSMContext):
    await state.update_data(date=callback.data.split(":")[1])
    data = await state.get_data()
    if data["record_type"] == "rental":
        await state.set_state(AddSchedule.waiting_time)
        await callback.message.edit_text("Выберите время:", reply_markup=get_times_keyboard())
    else:
        await state.set_state(AddSchedule.waiting_task_horse)
        await callback.message.edit_text("Введите кличку лошади:")
    await callback.answer()

# --- ВЕТКА ПРОКАТА ---
@router.callback_query(F.data.startswith("time_pick:"), AddSchedule.waiting_time)
async def process_time(callback: CallbackQuery, state: FSMContext):
    await state.update_data(time_slot=callback.data.split(":")[1])
    await state.set_state(AddSchedule.waiting_rental_type)
    await callback.message.edit_text("Выберите тип проката:", reply_markup=get_rental_type_keyboard())
    await callback.answer()

@router.callback_query(F.data.startswith("type_pick:"), AddSchedule.waiting_rental_type)
async def process_rental_type(callback: CallbackQuery, state: FSMContext):
    await state.update_data(task_type=callback.data.split(":")[1])
    await state.set_state(AddSchedule.waiting_duration)
    await callback.message.edit_text("Выберите длительность:", reply_markup=get_durations_keyboard())
    await callback.answer()

@router.callback_query(F.data.startswith("dur_pick:"), AddSchedule.waiting_duration)
async def process_duration(callback: CallbackQuery, state: FSMContext):
    await state.update_data(duration=callback.data.split(":")[1])
    await state.set_state(AddSchedule.waiting_instr_count)
    await callback.message.edit_text("Сколько нужно инструкторов?", reply_markup=get_instructors_count_keyboard())
    await callback.answer()

@router.callback_query(F.data.startswith("instr_count:"), AddSchedule.waiting_instr_count)
async def process_instr_count(callback: CallbackQuery, state: FSMContext):
    count = int(callback.data.split(":")[1])
    data = await state.get_data()
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("SELECT id FROM schedule WHERE date=? AND time_slot=? AND record_type='rental' AND deleted_at IS NULL", (data["date"], data["time_slot"]))
        if c.fetchone():
            await callback.message.edit_text("⚠️ На это время уже есть прокат.")
            await state.clear()
            return
        c.execute("INSERT INTO schedule (record_type, date, time_slot, task_type, duration, required_instructors, created_by, created_by_name, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                  ('rental', data["date"], data["time_slot"], data["task_type"], data["duration"], count, str(callback.from_user.id), callback.from_user.full_name, ts_msk()))
        conn.commit()
    finally: conn.close()
    log_action(c.lastrowid, "create_rental", callback.from_user.full_name, str(data))
    await callback.message.edit_text(f"✅ Слот проката создан!\n📅 {data['date']} 🕒 {data['time_slot']}\n🏇 {data['task_type']} ({data['duration']})\n👤 Нужно: {count}", parse_mode="HTML")
    await state.clear()

# --- ВЕТКА ПОРУЧЕНИЙ ---
@router.message(AddSchedule.waiting_task_horse)
async def process_task_horse(message: Message, state: FSMContext):
    await state.update_data(horse_name=message.text.strip())
    await state.set_state(AddSchedule.waiting_task_desc)
    await message.answer("Что нужно сделать (например: почистить, подковать, вывести на прогулку)?")

@router.message(AddSchedule.waiting_task_desc)
async def process_task_desc(message: Message, state: FSMContext):
    await state.update_data(task_type=message.text.strip())
    data = await state.get_data()
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("INSERT INTO schedule (record_type, date, task_type, horse_name, created_by, created_by_name, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                  ('task', data["date"], data["task_type"], data["horse_name"], str(message.from_user.id), message.from_user.full_name, ts_msk()))
        conn.commit()
    finally: conn.close()
    log_action(c.lastrowid, "create_task", message.from_user.full_name, str(data))
    await message.answer(f"✅ Поручение создано!\n📅 {data['date']}\n🐎 {data['horse_name']}: {data['task_type']}", parse_mode="HTML")
    await state.clear()

# ============================================================
# КАРТОЧКА ЗАПИСИ
# ============================================================
@router.callback_query(F.data.startswith("edit:"))
async def show_card(callback: CallbackQuery):
    row_id = int(callback.data.split(":")[1])
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("SELECT record_type, date, time_slot, task_type, duration, horse_name, required_instructors, assigned_instructors FROM schedule WHERE id = ? AND deleted_at IS NULL", (row_id,))
        row = c.fetchone()
    finally: conn.close()
    if not row: return await callback.answer("Не найдено.")
    
    r_type, date, time_slot, task, dur, horse, req, assigned = row
    assigned_text = assigned if assigned else "❌ Пока никто"
    assigned_list = [x.strip() for x in assigned.split(",") if x.strip()] if assigned else []
    user_name = callback.from_user.full_name or str(callback.from_user.id)
    
    btn_rows = []
    if r_type == 'rental':
        text = f"📝 <b>Прокат #{row_id}</b>\n\n📅 {date} 🕒 {time_slot}\n🏇 {task} ({dur})\n👤 Нужно: <b>{req}</b>\n✅ Взяли: <b>{assigned_text}</b>"
        if len(assigned_list) < req: btn_rows.append([InlineKeyboardButton(text="🙋‍♂️ Я возьму", callback_data=f"take:{row_id}")])
        if user_name in assigned_list: btn_rows.append([InlineKeyboardButton(text="❌ Отказаться", callback_data=f"untake:{row_id}")])
    else:
        text = f"📝 <b>Поручение #{row_id}</b>\n\n📅 {date}\n🐎 Лошадь: {horse}\n📋 Задача: {task}\n✅ Сделает: <b>{assigned_text}</b>"
        if user_name not in assigned_list: btn_rows.append([InlineKeyboardButton(text="✅ Я сделаю", callback_data=f"take:{row_id}")])
        if user_name in assigned_list: btn_rows.append([InlineKeyboardButton(text="❌ Отказаться", callback_data=f"untake:{row_id}")])

    btn_rows.append([InlineKeyboardButton(text="✏️ Изменить дату", callback_data=f"field:{row_id}:date")])
    if r_type == 'rental':
        btn_rows.append([InlineKeyboardButton(text="✏️ Изменить время", callback_data=f"field:{row_id}:time_slot")])
    btn_rows.append([InlineKeyboardButton(text="🗑 Удалить", callback_data=f"softdel:{row_id}")])

    keyboard = InlineKeyboardMarkup(inline_keyboard=btn_rows)
    with suppress(TelegramBadRequest): await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()

# ============================================================
# ВЗЯТЬ / ОТКАЗАТЬСЯ
# ============================================================
@router.callback_query(F.data.startswith("take:"))
async def take_slot(callback: CallbackQuery):
    row_id = int(callback.data.split(":")[1])
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("SELECT name FROM employees WHERE tg_id = ?", (callback.from_user.id,))
        emp = c.fetchone()
        name = emp[0] if emp else (callback.from_user.full_name or str(callback.from_user.id))
            
        c.execute("SELECT required_instructors, assigned_instructors FROM schedule WHERE id = ?", (row_id,))
        req, assigned = c.fetchone()
        alist = [x.strip() for x in assigned.split(",") if x.strip()] if assigned else []
        
        if name in alist: return await callback.answer("Вы уже записаны!", show_alert=True)
        if req > 0 and len(alist) >= req and len(alist) > 0: return await callback.answer("Мест нет.", show_alert=True)
            
        alist.append(name)
        conn.execute("UPDATE schedule SET assigned_instructors = ?, updated_at = ?, updated_by = ? WHERE id = ?", (", ".join(alist), ts_msk(), name, row_id))
        conn.commit()
    finally: conn.close()
    log_action(row_id, "assign", name, "Взял")
    await callback.answer("✅ Записано!")
    await show_card(callback)

@router.callback_query(F.data.startswith("untake:"))
async def untake_slot(callback: CallbackQuery):
    row_id = int(callback.data.split(":")[1])
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("SELECT name FROM employees WHERE tg_id = ?", (callback.from_user.id,))
        emp = c.fetchone()
        name = emp[0] if emp else (callback.from_user.full_name or str(callback.from_user.id))
            
        c.execute("SELECT assigned_instructors FROM schedule WHERE id = ?", (row_id,))
        alist = [x.strip() for x in c.fetchone()[0].split(",") if x.strip()]
        if name in alist:
            alist.remove(name)
            conn.execute("UPDATE schedule SET assigned_instructors = ?, updated_at = ?, updated_by = ? WHERE id = ?", (", ".join(alist), ts_msk(), name, row_id))
            conn.commit()
    finally: conn.close()
    log_action(row_id, "unassign", name, "Отказался")
    await callback.answer("❌ Отписались.")
    await show_card(callback)

# ============================================================
# РЕДАКТИРОВАНИЕ ДАТЫ/ВРЕМЕНИ И УДАЛЕНИЕ
# ============================================================
class EditField(StatesGroup):
    waiting_val = State()

@router.callback_query(F.data.startswith("field:"))
async def start_edit(callback: CallbackQuery, state: FSMContext):
    _, row_id, field = callback.data.split(":")
    await state.update_data(row_id=int(row_id), field=field)
    await state.set_state(EditField.waiting_val)
    if field == "date": await callback.message.answer("Выберите дату:", reply_markup=get_dates_keyboard())
    elif field == "time_slot": await callback.message.answer("Выберите время:", reply_markup=get_times_keyboard())
    await callback.answer()

@router.callback_query(F.data.startswith("date_pick:"), EditField.waiting_val)
@router.callback_query(F.data.startswith("time_pick:"), EditField.waiting_val)
async def apply_edit(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    conn = get_db()
    try:
        conn.execute(f"UPDATE schedule SET {data['field']} = ?, updated_at = ? WHERE id = ?", (callback.data.split(":")[1], ts_msk(), data['row_id']))
        conn.commit()
    finally: conn.close()
    await callback.message.edit_text("✅ Обновлено.")
    await state.clear()
    await callback.answer()

@router.callback_query(F.data.startswith("softdel:"))
async def softdel(callback: CallbackQuery):
    row_id = int(callback.data.split(":")[1])
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Да", callback_data=f"delconf:{row_id}"),
        InlineKeyboardButton(text="❌ Нет", callback_data=f"edit:{row_id}")
    ]])
    await callback.message.edit_text(f"Удалить #{row_id}?", reply_markup=kb)
    await callback.answer()

@router.callback_query(F.data.startswith("delconf:"))
async def delconf(callback: CallbackQuery):
    row_id = int(callback.data.split(":")[1])
    conn = get_db()
    try:
        conn.execute("UPDATE schedule SET deleted_at = ?, deleted_by = ? WHERE id = ?", (ts_msk(), callback.from_user.full_name, row_id))
        conn.commit()
    finally: conn.close()
    await callback.message.edit_text("🗑 Удалено.")
    await callback.answer()

# ============================================================
# /edit
# ============================================================
@router.message(Command("edit"))
async def cmd_edit(message: Message):
    today = today_msk()
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("SELECT id, record_type, date, time_slot, task_type FROM schedule WHERE date >= ? AND deleted_at IS NULL ORDER BY date, time_slot LIMIT 20", (today,))
        rows = c.fetchall()
    finally: conn.close()
    if not rows: return await message.answer("Записей нет.")
    buttons = []
    for r in rows:
        _, r_type, date, time_slot, task = r
        icon = "🏇" if r_type == 'rental' else "🐎"
        buttons.append([InlineKeyboardButton(text=f"{icon} {date} {time_slot} | {task}"[:60], callback_data=f"edit:{r[0]}")])
    await message.answer("Выберите запись:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

# ============================================================
# /register
# ============================================================
class Register(StatesGroup):
    waiting_name = State()

@router.message(Command("register"))
async def cmd_register(message: Message, state: FSMContext):
    await state.set_state(Register.waiting_name)
    await message.answer("Введите ваше имя так, как оно будет отображаться в боте:")

@router.message(Register.waiting_name)
async def process_register(message: Message, state: FSMContext):
    name = message.text.strip()
    conn = get_db()
    try:
        conn.execute("INSERT OR REPLACE INTO employees (tg_id, name) VALUES (?, ?)", (message.from_user.id, name))
        conn.commit()
    finally: conn.close()
    await message.answer(f"✅ Имя «{name}» привязано.")
    await state.clear()

# ============================================================
# /log, /revoke, /trash (для админа)
# ============================================================
@router.message(Command("log"))
async def cmd_log(message: Message):
    if not is_chief_admin(message.from_user.id): return await message.answer("⛔ Нет прав.")
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("SELECT timestamp, action, schedule_id, actor FROM audit_log ORDER BY id DESC LIMIT 30")
        rows = c.fetchall()
    finally: conn.close()
    if not rows: return await message.answer("Журнал пуст.")
    lines = ["📋 Последние действия:"]
    for ts, action, sid, actor in rows: lines.append(f"{ts} | #{sid} | {actor} | {action}")
    await message.answer("\n".join(lines))

@router.message(Command("revoke"))
async def cmd_revoke(message: Message):
    if not is_chief_admin(message.from_user.id): return await message.answer("⛔ Нет прав.")
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip().isdigit(): return await message.answer("Использование: /revoke <tg_id>")
    target_id = int(parts[1].strip())
    if target_id in CHIEF_ADMIN_IDS: return await message.answer("⛔ Нельзя отозвать у админа.")
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("DELETE FROM auth_users WHERE tg_id = ?", (target_id,))
        deleted = c.rowcount
        conn.commit()
    finally: conn.close()
    await message.answer(f"✅ Доступ {target_id} отозван." if deleted else f"Пользователь не найден.")

# ============================================================
# /trash
# ============================================================
@router.message(Command("trash"))
async def cmd_trash(message: Message):
    if not is_chief_admin(message.from_user.id): return await message.answer("⛔ Нет прав.")
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("SELECT id, record_type, date, task_type FROM schedule WHERE deleted_at IS NOT NULL LIMIT 20")
        rows = c.fetchall()
    finally: conn.close()
    if not rows: return await message.answer("Корзина пуста.")
    buttons = [[InlineKeyboardButton(text=f"♻️ {r[2]} | {r[3]}"[:60], callback_data=f"restore:{r[0]}")] for r in rows]
    await message.answer("Корзина:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@router.callback_query(F.data.startswith("restore:"))
async def restore(callback: CallbackQuery):
    if not is_chief_admin(callback.from_user.id): return await callback.answer("⛔ Нет прав.")
    row_id = int(callback.data.split(":")[1])
    conn = get_db()
    try:
        conn.execute("UPDATE schedule SET deleted_at = NULL WHERE id = ?", (row_id,))
        conn.commit()
    finally: conn.close()
    await callback.message.edit_text("♻️ Восстановлено.")
    await callback.answer()

# ============================================================
# ТОЧКА ВХОДА
# ============================================================
async def main():
    init_db()
    print("Бот запущен.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())