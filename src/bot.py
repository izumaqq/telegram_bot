import asyncio
import aiosqlite
import os
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters.command import Command
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(id.strip()) for id in os.getenv("ADMIN_IDS", "0").split(",") if id.strip()]
DB_PATH = os.getenv("DB_PATH", "bookings.db")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN not found in environment variables")

# Useful startup info
print(f"Using DB path: {DB_PATH}")

def is_admin(user_id):
    return user_id in ADMIN_IDS

bot = Bot(BOT_TOKEN)
dp = Dispatcher()

# in-memory state for pending review submissions
pending_reviews = set()
# in-memory state for pending admin range selections {admin_id: {stage: 'start'|'end', start: 'YYYY-MM-DD'}}
pending_range = {}

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            name TEXT,
            date TEXT,
            time TEXT,
            comment TEXT
        )
        """)
        # Ensure new columns exist if the table was created earlier
        cursor = await db.execute("PRAGMA table_info(bookings)")
        cols = await cursor.fetchall()
        col_names = {c[1] for c in cols}
        if 'time' not in col_names:
            try:
                await db.execute("ALTER TABLE bookings ADD COLUMN time TEXT")
            except Exception:
                pass
        if 'comment' not in col_names:
            try:
                await db.execute("ALTER TABLE bookings ADD COLUMN comment TEXT")
            except Exception:
                pass
        await db.commit()
        # create reviews table
        await db.execute("""
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            name TEXT,
            text TEXT,
            created_at TEXT
        )
        """)
        # table for blocked dates (admin can block/unblock specific dates)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS blocked_dates (
            date TEXT PRIMARY KEY
        )
        """)
        # table for recurring closed weekdays (0=Mon..6=Sun)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS closed_weekdays (
            weekday INTEGER PRIMARY KEY
        )
        """)
        await db.commit()

import calendar

async def build_calendar(year: int = None, month: int = None, months: int = 2, booking_id: int = 0, admin_mode: bool = False):
    """
    Build an inline keyboard calendar that can render multiple sequential months when `months` > 1.
    - dates outside allowed range are disabled
    - dates with >=2 bookings are marked as full and disabled
    - dates with 1 booking show (1/2)
    - admin_mode=True will show blocked dates and allow toggling and includes admin controls in the same keyboard
    """
    today = datetime.now().date()
    if year is None or month is None:
        year = today.year
        month = today.month

    min_date = today
    max_date = today + timedelta(days=30 * months)

    keyboard = []

    async with aiosqlite.connect(DB_PATH) as db:
        # fetch closed weekdays (recurring non-working days)
        cursor = await db.execute("SELECT weekday FROM closed_weekdays")
        rows = await cursor.fetchall()
        closed_wd = {r[0] for r in rows}

        # render sequential months
        for offset in range(months):
            cur_month = month + offset
            cur_year = year
            # normalize month/year
            while cur_month > 12:
                cur_month -= 12
                cur_year += 1

            # month header
            header_row = [InlineKeyboardButton(text=f"{calendar.month_name[cur_month]} {cur_year}", callback_data="noop")]
            keyboard.append(header_row)

            cal_matrix = calendar.monthcalendar(cur_year, cur_month)
            # Weekday headers (only once per month)
            weekday_names = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
            keyboard.append([InlineKeyboardButton(text=wd, callback_data="noop") for wd in weekday_names])

            for week in cal_matrix:
                row = []
                for day in week:
                    if day == 0:
                        row.append(InlineKeyboardButton(text=" ", callback_data="noop"))
                    else:
                        d = datetime(cur_year, cur_month, day).date()
                        if d < min_date or d > max_date:
                            row.append(InlineKeyboardButton(text=str(day), callback_data="cal_disabled"))
                        else:
                            # check blocked (single-date blocks)
                            cursor = await db.execute("SELECT 1 FROM blocked_dates WHERE date = ?", (d.isoformat(),))
                            blocked = await cursor.fetchone() is not None
                            # check if this weekday is globally closed
                            week_closed = d.weekday() in closed_wd
                            # check booking count
                            cursor = await db.execute("SELECT COUNT(*) FROM bookings WHERE date = ?", (d.strftime("%d.%m.%Y"),))
                            cnt = (await cursor.fetchone())[0]

                            # Represent closed weekdays as blocked for users
                            if admin_mode:
                                text = f"{d.day}"
                                if blocked or week_closed:
                                    text = f"⛔{d.day}"
                                    cb = f"toggle_block_{d.isoformat()}"
                                else:
                                    if cnt >= 2:
                                        text = f"🔴{d.day}"
                                    elif cnt == 1:
                                        text = f"{d.day} (1/2)"
                                    cb = f"toggle_block_{d.isoformat()}"
                                row.append(InlineKeyboardButton(text=text, callback_data=cb))
                            else:
                                if blocked or week_closed:
                                    row.append(InlineKeyboardButton(text=f"⛔{d.day}", callback_data="cal_blocked"))
                                else:
                                    if cnt >= 2:
                                        row.append(InlineKeyboardButton(text=f"🔴{d.day}", callback_data="cal_disabled"))
                                    elif cnt == 1:
                                        cb = f"cal_day_{d.isoformat()}_{booking_id}"
                                        row.append(InlineKeyboardButton(text=f"{d.day} (1/2)", callback_data=cb))
                                    else:
                                        cb = f"cal_day_{d.isoformat()}_{booking_id}"
                                        row.append(InlineKeyboardButton(text=str(d.day), callback_data=cb))
                keyboard.append(row)

        # Navigation row for the first month (keeps previous behaviour)
        prev_month_date = (datetime(year, month, 1) - timedelta(days=1))
        next_month_date = (datetime(cur_year, cur_month, calendar.monthrange(cur_year, cur_month)[1]) + timedelta(days=1))

        nav_row = []
        nav_row.append(InlineKeyboardButton(text="◀️", callback_data=f"cal_month_{prev_month_date.year}_{prev_month_date.month}_{months}_{int(admin_mode)}"))
        nav_row.append(InlineKeyboardButton(text=f"{calendar.month_name[month]} {year}", callback_data=f"choose_month_{year}_{int(admin_mode)}"))
        nav_row.append(InlineKeyboardButton(text="▶️", callback_data=f"cal_month_{next_month_date.year}_{next_month_date.month}_{months}_{int(admin_mode)}"))

        keyboard.append(nav_row)

        # Months range selector + choose month
        keyboard.append([
            InlineKeyboardButton(text="Выбрать месяц", callback_data=f"choose_month_{year}_{int(admin_mode)}"),
            InlineKeyboardButton(text="1 мес", callback_data=f"cal_set_1_{int(admin_mode)}"),
            InlineKeyboardButton(text="2 мес", callback_data=f"cal_set_2_{int(admin_mode)}")
        ])

        # If admin mode, add admin controls directly in the same keyboard (single message)
        if admin_mode:
            keyboard.append([
                InlineKeyboardButton(text="⚠️ Блокировать диапазон", callback_data="admin_block_range"),
                InlineKeyboardButton(text="⛔ Очистить блокировки", callback_data="admin_clear_blocks")
            ])
            keyboard.append([InlineKeyboardButton(text="Назад", callback_data="admin")])

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


@dp.callback_query(lambda c: c.data.startswith("cal_set_"))
async def cal_set_months(call: types.CallbackQuery):
    try:
        parts = call.data.replace("cal_set_", "").split("_")
        months = int(parts[0])
        admin_mode = bool(int(parts[1])) if len(parts) > 1 else False
        markup = await build_calendar(months=months, admin_mode=admin_mode)
        try:
            await call.message.edit_text("📅 Выберите дату:", reply_markup=markup)
        except Exception as e:
            if "message is not modified" not in str(e).lower():
                print(f"Error editing message in cal_set_months: {e}")
        await call.answer()
    except Exception as e:
        if "message is not modified" in str(e).lower():
            # ignore harmless Telegram 'message is not modified' errors
            pass
        else:
            print(f"Error in cal_set_months: {e}")
        await call.answer()


@dp.callback_query(lambda c: c.data.startswith("cal_month_"))
async def cal_month_nav(call: types.CallbackQuery):
    try:
        parts = call.data.replace("cal_month_", "").split("_")
        year = int(parts[0])
        month = int(parts[1])
        months = int(parts[2])
        admin_mode = bool(int(parts[3])) if len(parts) > 3 else False
        markup = await build_calendar(year=year, month=month, months=months, admin_mode=admin_mode)
        try:
            await call.message.edit_text("📅 Выберите дату:", reply_markup=markup)
        except Exception as e:
            if "message is not modified" not in str(e).lower():
                print(f"Error editing message in cal_month_nav: {e}")
        await call.answer()
    except Exception as e:
        if "message is not modified" in str(e).lower():
            pass
        else:
            print(f"Error in cal_month_nav: {e}")
        await call.answer()


@dp.callback_query(lambda c: c.data.startswith("choose_month_"))
async def choose_month(call: types.CallbackQuery):
    try:
        parts = call.data.replace("choose_month_", "").split("_")
        year = int(parts[0])
        admin_mode = bool(int(parts[1])) if len(parts) > 1 else False
        # build a grid of months for the year
        buttons = []
        row = []
        for m in range(1, 13):
            row.append(InlineKeyboardButton(text=f"{m}", callback_data=f"goto_month_{year}_{m}_{int(admin_mode)}"))
            if len(row) == 4:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)

        # year navigation
        buttons.append([
            InlineKeyboardButton(text="◀️", callback_data=f"choose_month_{year-1}_{int(admin_mode)}"),
            InlineKeyboardButton(text=f"{year}", callback_data="noop"),
            InlineKeyboardButton(text="▶️", callback_data=f"choose_month_{year+1}_{int(admin_mode)}")
        ])

        try:
            await call.message.edit_text(f"Выберите месяц: {year}", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        except Exception as e:
            if "message is not modified" not in str(e).lower():
                print(f"Error editing message in choose_month: {e}")
        await call.answer()
    except Exception as e:
        if "message is not modified" in str(e).lower():
            pass
        else:
            print(f"Error in choose_month: {e}")
        await call.answer() 


@dp.callback_query(lambda c: c.data.startswith("goto_month_"))
async def goto_month(call: types.CallbackQuery):
    try:
        parts = call.data.replace("goto_month_", "").split("_")
        year = int(parts[0])
        month = int(parts[1])
        admin_mode = bool(int(parts[2])) if len(parts) > 2 else False
        markup = await build_calendar(year=year, month=month, months=1, admin_mode=admin_mode)
        try:
            await call.message.edit_text("📅 Выберите дату:", reply_markup=markup)
        except Exception as e:
            if "message is not modified" not in str(e).lower():
                print(f"Error editing message in goto_month: {e}")
        await call.answer()
    except Exception as e:
        if "message is not modified" in str(e).lower():
            pass
        else:
            print(f"Error in goto_month: {e}")
        await call.answer()


@dp.callback_query(lambda c: c.data.startswith("cal_day_"))
async def cal_day_select(call: types.CallbackQuery):
    print(f"cal_day_select invoked: {call.data} by {getattr(call.from_user, 'id', None)}")
    try:
        payload = call.data.replace("cal_day_", "")
        date_str, booking_id_str = payload.rsplit("_", 1)
        booking_id = int(booking_id_str)

        # check blocked
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("SELECT 1 FROM blocked_dates WHERE date = ?", (date_str,))
            if await cursor.fetchone():
                await call.answer("Эта дата заблокирована", show_alert=True)
                return

        if booking_id == 0:
            await call.message.answer(f"Вы выбрали дату: {date_str}\nВыберите время:", reply_markup=time_keyboard(date_str))
        else:
            async with aiosqlite.connect(DB_PATH) as db:
                cursor = await db.execute("SELECT user_id, name FROM bookings WHERE id = ?", (booking_id,))
                row = await cursor.fetchone()
                if row:
                    user_id, name = row
                    await db.execute("UPDATE bookings SET date = ? WHERE id = ?", (date_str, booking_id))
                    await db.commit()
                    await call.message.answer(f"✅ Обновлено: {name} → {date_str}")
                    try:
                        await bot.send_message(user_id, f"📅 Ваша запись перенесена на {date_str}")
                    except:
                        pass
                else:
                    await call.message.answer("❌ Запись не найдена")
        await call.answer()
    except Exception as e:
        print(f"Error in cal_day_select: {e}")
        await call.answer("❌ Ошибка")


@dp.callback_query(lambda c: c.data == "cal_disabled")
async def cal_disabled(call: types.CallbackQuery):
    await call.answer("Нельзя выбрать эту дату", show_alert=True)


@dp.callback_query(lambda c: c.data == "cal_blocked")
async def cal_blocked(call: types.CallbackQuery):
    await call.answer("Дата недоступна по расписанию", show_alert=True)


def time_keyboard(date: str):
    # fixed time slots — you can change these
    times = ["10:00", "11:00", "12:00", "14:00", "15:00", "16:00"]
    buttons = []
    for t in times:
        buttons.append([InlineKeyboardButton(text=t, callback_data=f"time_{date}_{t}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def admin_keyboard():
    # make date management more prominent at the top
    buttons = [
        [InlineKeyboardButton(text="🛑 Управление датами", callback_data="admin_dates")],
        [InlineKeyboardButton(text="📆 Управление днями недели", callback_data="admin_weekdays")],
        [InlineKeyboardButton(text="📋 Просмотреть все записи", callback_data="admin_view")],
        [InlineKeyboardButton(text="❌ Отменить запись", callback_data="admin_cancel")],
        [InlineKeyboardButton(text="✏️ Изменить дату записи", callback_data="admin_edit")],
        [InlineKeyboardButton(text="📝 Отзывы", callback_data="admin_reviews")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)



def main_keyboard():
    buttons = [
        [InlineKeyboardButton(text="📞 Связаться", callback_data="contact")],
        [InlineKeyboardButton(text="🛠 Мои работы", callback_data="mywork")],
        [InlineKeyboardButton(text="💬 Отзывы", callback_data="reviews")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@dp.message(Command("start"))
async def start(message: types.Message):
    try:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Полный календарь", callback_data="range_full")],
            [InlineKeyboardButton(text="На 1 месяц", callback_data="range_1"), InlineKeyboardButton(text="На 2 месяца", callback_data="range_2")]
        ])
        await message.answer("📅 Выберите диапазон дат:", reply_markup=kb)
        await message.answer("Быстрые команды:", reply_markup=main_keyboard())
    except Exception as e:
        print(f"Error in start command: {e}")
        await message.answer("❌ Произошла ошибка")


@dp.callback_query(lambda c: c.data.startswith("range_"))
async def range_selected(call: types.CallbackQuery):
    print(f"range_selected invoked: {call.data} by {getattr(call.from_user, 'id', None)}")
    try:
        key = call.data.replace("range_", "")
        if key == "full":
            months = 12
        else:
            try:
                months = int(key)
            except ValueError:
                print(f"Invalid range value: {key}")
                await call.answer()
                return

        markup = await build_calendar(months=months, booking_id=0)
        try:
            await call.message.answer("📅 Выберите дату:", reply_markup=markup)
        except Exception as e:
            if "message is not modified" not in str(e).lower():
                print(f"Error sending calendar in range_selected: {e}")
        await call.answer()
    except Exception as e:
        print(f"Error in range_selected: {e}")
        await call.answer()


@dp.callback_query(lambda c: c.data == "range_full")
async def range_full(call: types.CallbackQuery):
    try:
        # full calendar view: allow 12 months ahead
        markup = await build_calendar(months=12, booking_id=0)
        try:
            await call.message.answer("📅 Выберите дату:", reply_markup=markup)
        except Exception as e:
            if "message is not modified" not in str(e).lower():
                print(f"Error in range_full: {e}")
        await call.answer()
    except Exception as e:
        print(f"Error in range_full: {e}")
        await call.answer()



@dp.callback_query(lambda c: c.data.startswith("date_"))
async def date_selected(call: types.CallbackQuery):
    try:
        date = call.data.replace("date_", "")
        # ask user to choose time after date
        await call.message.answer(f"Вы выбрали дату: {date}\nВыберите время:", reply_markup=time_keyboard(date))
        await call.answer()
    except Exception as e:
        print(f"Error in date_selected: {e}")
        await call.message.answer("❌ Ошибка")
        await call.answer()


@dp.callback_query(lambda c: c.data.startswith("time_"))
async def time_selected(call: types.CallbackQuery):
    try:
        payload = call.data.replace("time_", "")
        # payload = "{date_iso}_{time}"
        parts = payload.rsplit("_", 1)
        date_iso = parts[0]
        time = parts[1]

        # check blocked and counts
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("SELECT 1 FROM blocked_dates WHERE date = ?", (date_iso,))
            if await cursor.fetchone():
                await call.answer("Эта дата заблокирована", show_alert=True)
                return

            # check recurring closed weekdays
            wd = datetime.fromisoformat(date_iso).weekday()
            cursor = await db.execute("SELECT 1 FROM closed_weekdays WHERE weekday = ?", (wd,))
            if await cursor.fetchone():
                await call.answer("В этот день я не работаю", show_alert=True)
                return

            # bookings store date as DD.MM.YYYY
            date_display = datetime.fromisoformat(date_iso).strftime("%d.%m.%Y")
            cursor = await db.execute("SELECT COUNT(*) FROM bookings WHERE date = ?", (date_display,))
            cnt = (await cursor.fetchone())[0]
            if cnt >= 2:
                await call.answer("На эту дату уже записано максимальное количество людей", show_alert=True)
                return

            # check if this time is already taken on that date
            cursor = await db.execute("SELECT 1 FROM bookings WHERE date = ? AND time = ?", (date_display, time))
            if await cursor.fetchone():
                await call.answer("Это время уже занято", show_alert=True)
                return

            await db.execute(
                "INSERT INTO bookings (user_id, name, date, time, comment) VALUES (?, ?, ?, ?, ?)",
                (call.from_user.id, call.from_user.first_name, date_display, time, None)
            )
            await db.commit()

        await call.message.answer(f"✅ Вы записаны на {date_display} в {time}.\nНапишите комментарий к записи или отправьте /skip, чтобы пропустить.")
        # notify admins
        if ADMIN_IDS:
            for admin_id in ADMIN_IDS:
                try:
                    await bot.send_message(admin_id, f"📌 Новая запись:\n👤 {call.from_user.first_name}\n📅 {date_display} {time}")
                except:
                    pass
        await call.answer()
    except Exception as e:
        print(f"Error in time_selected: {e}")
        await call.message.answer("❌ Ошибка при сохранении записи")
        await call.answer()


@dp.callback_query(lambda c: c.data == "contact")
async def contact_info(call: types.CallbackQuery):
    try:
        await call.message.answer("📞 Контакты администратора:\n@simbviska\nID: 1076207542")
        await call.answer()
    except Exception as e:
        print(f"Error in contact_info: {e}")
        await call.answer()


@dp.callback_query(lambda c: c.data == "mywork")
async def my_work(call: types.CallbackQuery):
    try:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📱 Instagram", url="https://www.instagram.com/vii.nail_?igsh=MThlZDM4OWt0M2FzdQ%3D%3D&utm_source=qr")],
            [InlineKeyboardButton(text="💬 Telegram", url="https://t.me/vii_nails_art")]
        ])
        await call.message.answer("🛠 Мои работы и отзывы:", reply_markup=keyboard)
        await call.answer()
    except Exception as e:
        print(f"Error in my_work: {e}")
        await call.answer()


@dp.callback_query(lambda c: c.data == "reviews")
async def show_reviews(call: types.CallbackQuery):
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("SELECT name, text, created_at FROM reviews ORDER BY id DESC LIMIT 10")
            rows = await cursor.fetchall()

        text = "💬 Отзывы:\n\n"
        if not rows:
            text = "Пока нет отзывов."
        else:
            for name, text_rev, created in rows:
                text += f"👤 {name}: {text_rev} ({created})\n\n"

        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Оставить отзыв", callback_data="leave_review")]])
        await call.message.answer(text, reply_markup=kb)
        await call.answer()
    except Exception as e:
        print(f"Error in show_reviews: {e}")
        await call.answer()


@dp.callback_query(lambda c: c.data == "leave_review")
async def leave_review_cb(call: types.CallbackQuery):
    try:
        pending_reviews.add(call.from_user.id)
        await call.message.answer("Напишите, пожалуйста, ваш отзыв в сообщении.")
        await call.answer()
    except Exception as e:
        print(f"Error in leave_review_cb: {e}")
        await call.answer()


@dp.message(Command("review"))
async def review_cmd(message: types.Message):
    pending_reviews.add(message.from_user.id)
    await message.reply("Напишите, пожалуйста, ваш отзыв в сообщении.")


@dp.message(Command("admin"))
async def admin_panel(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Доступ запрещён")
        return

    kb = admin_keyboard()
    # log keyboard rows for debugging (admins only)
    try:
        keys = []
        for row in kb.inline_keyboard:
            keys.append([b.text for b in row])
        print(f"Admin keyboard sent to {message.from_user.id}: {keys}")
    except Exception as e:
        print(f"Error dumping admin keyboard: {e}")

    await message.answer("🔧 Панель администратора", reply_markup=kb)
    # fallback in case client hides buttons: provide command hint
    await message.answer("Если вы не видите кнопку '🛑 Управление датами', введите /admin_dates")



@dp.callback_query(lambda c: c.data == "admin_view")
async def admin_view_all(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("❌ Доступ запрещён")
        return

    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("SELECT id, name, date, time, comment FROM bookings")
            rows = await cursor.fetchall()

        if not rows:
            await call.message.answer("Записей пока нет.")
            return

        text = "📋 Все записи:\n\n"
        for row_id, name, date, time, comment in rows:
            text += f"ID: {row_id}\n👤 {name}\n📅 {date} {time}\nКомментарий: {comment if comment else '-'}\n\n"

        await call.message.answer(text)
    except Exception as e:
        print(f"Error in admin_view_all: {e}")
        await call.message.answer("❌ Ошибка при получении записей")


@dp.callback_query(lambda c: c.data == "admin_reviews")
async def admin_show_reviews(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("❌ Доступ запрещён")
        return

    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("SELECT id, name, text, created_at FROM reviews ORDER BY id DESC LIMIT 50")
            rows = await cursor.fetchall()

        if not rows:
            await call.message.answer("Отзывы отсутствуют.")
            return

        text = "📝 Все отзывы:\n\n"
        for r_id, name, text_rev, created in rows:
            text += f"ID:{r_id} 👤 {name}: {text_rev} ({created})\n\n"

        await call.message.answer(text)
    except Exception as e:
        print(f"Error in admin_show_reviews: {e}")
        await call.message.answer("❌ Ошибка при получении отзывов")


@dp.callback_query(lambda c: c.data == "admin_cancel")
async def admin_cancel_booking(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("❌ Доступ запрещён")
        return

    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("SELECT id, name, date, time FROM bookings")
            rows = await cursor.fetchall()

        if not rows:
            await call.message.answer("Нет записей для отмены.")
            return

        buttons = []
        for row_id, name, date, time in rows:
            buttons.append([InlineKeyboardButton(
                text=f"Отменить: {name} ({date} {time})",
                callback_data=f"cancel_id_{row_id}"
            )])
        
        await call.message.answer("Выберите запись для отмены:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    except Exception as e:
        print(f"Error in admin_cancel_booking: {e}")
        await call.message.answer("❌ Error loading bookings")

@dp.callback_query(lambda c: c.data.startswith("cancel_id_"))
async def confirm_cancel(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("❌ Доступ запрещён")
        return

    try:
        booking_id = int(call.data.replace("cancel_id_", ""))
        
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("SELECT user_id, name, date, time FROM bookings WHERE id = ?", (booking_id,))
            row = await cursor.fetchone()
            
            if row:
                user_id, name, date, time = row
                await db.execute("DELETE FROM bookings WHERE id = ?", (booking_id,))
                await db.commit()
                
                await call.message.answer(f"✅ Отменено: {name} ({date} {time})")
                
                # Notify user
                try:
                    await bot.send_message(user_id, f"⚠️ Ваша запись на {date} {time} была отменена администратором")
                except:
                    pass
            else:
                await call.message.answer("❌ Запись не найдена")
    except Exception as e:
        print(f"Error in confirm_cancel: {e}")
        await call.message.answer("❌ Error cancelling booking")

@dp.callback_query(lambda c: c.data == "admin_edit")
async def admin_edit_booking(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("❌ Доступ запрещён")
        return

    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("SELECT id, name, date, time, comment FROM bookings")
            rows = await cursor.fetchall()

        if not rows:
            await call.message.answer("Нет записей для изменения.")
            return

        buttons = []
        for row_id, name, date, time, comment in rows:
            buttons.append([InlineKeyboardButton(
                text=f"Изменить: {name} ({date} {time})",
                callback_data=f"edit_id_{row_id}"
            )])
        
        await call.message.answer("Выберите запись для изменения:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    except Exception as e:
        print(f"Error in admin_edit_booking: {e}")
        await call.message.answer("❌ Error loading bookings")


@dp.callback_query(lambda c: c.data == "admin_dates")
async def admin_dates(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("❌ Доступ запрещён")
        return

    try:
        print(f"admin_dates callback invoked by {call.from_user.id}")
        markup = await build_calendar(months=1, admin_mode=True)
        await call.message.answer("Выберите дату для блокировки/разблокировки:", reply_markup=markup)
        await call.answer()
    except Exception as e:
        print(f"Error in admin_dates: {e}")
        await call.message.answer("❌ Error loading dates")


@dp.message(Command("admin_dates"))
async def admin_dates_cmd(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Доступ запрещён")
        return

    try:
        markup = await build_calendar(months=1, admin_mode=True)
        await message.answer("Выберите дату для блокировки/разблокировки:", reply_markup=markup)
    except Exception as e:
        print(f"Error in admin_dates_cmd: {e}")
        await message.answer("❌ Error loading dates")


@dp.callback_query(lambda c: c.data == "admin_weekdays")
async def admin_weekdays(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("❌ Доступ запрещён")
        return

    try:
        # show weekdays and their status
        days = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("SELECT weekday FROM closed_weekdays")
            rows = await cursor.fetchall()
            closed = {r[0] for r in rows}

        buttons = []
        row = []
        for i, d in enumerate(days):
            mark = "⛔" if i in closed else "✅"
            row.append(InlineKeyboardButton(text=f"{mark} {d}", callback_data=f"toggle_weekday_{i}"))
            if len(row) == 4:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)

        buttons.append([InlineKeyboardButton(text="Назад", callback_data="admin_back")])
        await call.message.answer("Управление рабочими днями: нажмите, чтобы переключить", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        await call.answer()
    except Exception as e:
        print(f"Error in admin_weekdays: {e}")
        await call.answer()


@dp.callback_query(lambda c: c.data.startswith("edit_id_"))
async def select_new_date(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("❌ Access denied")
        return

    booking_id = int(call.data.replace("edit_id_", ""))
    # default to 1 month range for admin edits
    markup = await build_calendar(months=1, booking_id=booking_id)
    try:
        await call.message.answer("Выберите новую дату:", reply_markup=markup)
    except Exception as e:
        if "message is not modified" not in str(e).lower():
            print(f"Error sending edit calendar: {e}")
    await call.answer()

@dp.callback_query(lambda c: c.data.startswith("new_date_"))
async def confirm_edit(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("❌ Access denied")
        return

    try:
        parts = call.data.replace("new_date_", "").split("_", 1)
        booking_id = int(parts[0])
        new_date = parts[1]
        
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("SELECT user_id, name FROM bookings WHERE id = ?", (booking_id,))
            row = await cursor.fetchone()
            
            if row:
                user_id, name = row
                await db.execute("UPDATE bookings SET date = ? WHERE id = ?", (new_date, booking_id))
                await db.commit()
                
                await call.message.answer(f"✅ Обновлено: {name} → {new_date}")
                
                # Notify user
                try:
                    await bot.send_message(user_id, f"📅 Ваша запись перенесена на {new_date}")
                except:
                    pass
            else:
                await call.message.answer("❌ Запись не найдена")
    except Exception as e:
        print(f"Error in confirm_edit: {e}")
        await call.message.answer("❌ Ошибка при обновлении записи")


@dp.callback_query(lambda c: c.data == "admin_block_range")
async def admin_block_range(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("❌ Доступ запрещён")
        return
    try:
        pending_range[call.from_user.id] = {"stage": "start", "start": None}
        # show calendar to pick start
        markup = await build_calendar(months=1, admin_mode=True)
        kb_cancel = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Отмена", callback_data="cancel_block_range")]])
        await call.message.answer("Выберите начальную дату диапазона:", reply_markup=markup)
        await call.message.answer("Или нажмите Отмена", reply_markup=kb_cancel)
        await call.answer()
    except Exception as e:
        print(f"Error in admin_block_range: {e}")
        await call.answer()


@dp.callback_query(lambda c: c.data == "cancel_block_range")
async def cancel_block_range(call: types.CallbackQuery):
    pending_range.pop(call.from_user.id, None)
    try:
        await call.answer("Операция отменена")
    except:
        pass


@dp.callback_query(lambda c: c.data.startswith("toggle_block_"))
async def toggle_block(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("❌ Доступ запрещён")
        return

    try:
        date_iso = call.data.replace("toggle_block_", "")

        # if admin is in pending_range flow
        pr = pending_range.get(call.from_user.id)
        if pr and pr.get("stage") == "start":
            pr["start"] = date_iso
            pr["stage"] = "end"
            await call.answer("Установлена начальная дата. Теперь выберите конечную дату.")
            return
        elif pr and pr.get("stage") == "end":
            start_iso = pr.get("start")
            end_iso = date_iso
            s = datetime.fromisoformat(start_iso).date()
            e = datetime.fromisoformat(end_iso).date()
            if e < s:
                s, e = e, s
            # create all dates between s and e inclusive
            d = s
            inserted = 0
            async with aiosqlite.connect(DB_PATH) as db:
                while d <= e:
                    try:
                        await db.execute("INSERT OR IGNORE INTO blocked_dates (date) VALUES (?)", (d.isoformat(),))
                        inserted += 1
                    except Exception as ex:
                        print(f"Error inserting blocked date {d}: {ex}")
                    d = d + timedelta(days=1)
                await db.commit()
            pending_range.pop(call.from_user.id, None)
            await call.answer(f"⛔ Заблокировано {inserted} дат")
            # refresh calendar
            try:
                now = datetime.now()
                markup = await build_calendar(months=1, year=now.year, month=now.month, admin_mode=True)
                await call.message.edit_text("Выберите дату для блокировки/разблокировки:", reply_markup=markup)
            except Exception as ex:
                print(f"Error refreshing calendar after range block: {ex}")
            return

        # regular toggle single date
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("SELECT 1 FROM blocked_dates WHERE date = ?", (date_iso,))
            if await cursor.fetchone():
                await db.execute("DELETE FROM blocked_dates WHERE date = ?", (date_iso,))
                await db.commit()
                await call.answer("✅ Дата разблокирована")
            else:
                await db.execute("INSERT INTO blocked_dates (date) VALUES (?)", (date_iso,))
                await db.commit()
                await call.answer("⛔ Дата заблокирована")

        # refresh calendar message preserving current month/year if possible
        try:
            now = datetime.now()
            markup = await build_calendar(months=1, year=now.year, month=now.month, admin_mode=True)
            await call.message.edit_text("Выберите дату для блокировки/разблокировки:", reply_markup=markup)
        except Exception as ex:
            print(f"Error refreshing calendar after toggle: {ex}")
    except Exception as e:
        import traceback
        print(f"Error in toggle_block: {e}\n{traceback.format_exc()}")
        try:
            await call.answer("❌ Ошибка")
        except:
            pass


@dp.callback_query(lambda c: c.data == "admin_clear_blocks")
async def admin_clear_blocks(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("❌ Доступ запрещён")
        return

    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("SELECT COUNT(*) FROM blocked_dates")
            cnt = (await cursor.fetchone())[0]
            await db.execute("DELETE FROM blocked_dates")
            await db.commit()
        await call.answer(f"✅ Удалено {cnt} блокировок")
        # refresh calendar
        try:
            now = datetime.now()
            markup = await build_calendar(months=1, year=now.year, month=now.month, admin_mode=True)
            await call.message.edit_text("Выберите дату для блокировки/разблокировки:", reply_markup=markup)
        except Exception as e:
            if "message is not modified" not in str(e).lower():
                print(f"Error refreshing calendar after clear blocks: {e}")
    except Exception as e:
        print(f"Error in admin_clear_blocks: {e}")
        await call.answer("❌ Ошибка при очистке блокировок")


@dp.callback_query(lambda c: c.data.startswith("toggle_weekday_"))
async def toggle_weekday(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("❌ Доступ запрещён")
        return

    try:
        wd = int(call.data.replace("toggle_weekday_", ""))
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("SELECT 1 FROM closed_weekdays WHERE weekday = ?", (wd,))
            if await cursor.fetchone():
                await db.execute("DELETE FROM closed_weekdays WHERE weekday = ?", (wd,))
                await db.commit()
                await call.answer("✅ День недели отмечен как рабочий")
            else:
                await db.execute("INSERT INTO closed_weekdays (weekday) VALUES (?)", (wd,))
                await db.commit()
                await call.answer("⛔ День недели отмечен как нерабочий")

        # refresh weekdays UI
        await admin_weekdays(call)
    except Exception as e:
        print(f"Error in toggle_weekday: {e}")
        await call.answer("❌ Ошибка")


@dp.message()
async def handle_comment(message: types.Message):
    # ignore commands
    if not message.text or message.text.startswith("/"):
        return

    # If user is leaving a review
    if message.from_user.id in pending_reviews:
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "INSERT INTO reviews (user_id, name, text, created_at) VALUES (?, ?, ?, ?)",
                    (message.from_user.id, message.from_user.first_name, message.text.strip(), datetime.now().isoformat())
                )
                await db.commit()

            pending_reviews.discard(message.from_user.id)
            await message.reply("✅ Спасибо за отзыв!")
            # notify admins
            if ADMIN_IDS:
                for admin_id in ADMIN_IDS:
                    try:
                        await bot.send_message(admin_id, f"🆕 Новый отзыв от {message.from_user.first_name}: {message.text.strip()}")
                    except:
                        pass
            return
        except Exception as e:
            print(f"Error saving review: {e}")
            await message.reply("❌ Ошибка при сохранении отзыва")
            pending_reviews.discard(message.from_user.id)
            return

    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute(
                "SELECT id FROM bookings WHERE user_id = ? AND comment IS NULL ORDER BY id DESC LIMIT 1",
                (message.from_user.id,)
            )
            row = await cursor.fetchone()

            if not row:
                await message.reply("Я не нашёл запись для добавления комментария. Отправьте /start, чтобы записаться.")
                return

            booking_id = row[0]
            await db.execute("UPDATE bookings SET comment = ? WHERE id = ?", (message.text.strip(), booking_id))
            await db.commit()

        await message.reply("✅ Комментарий сохранён. Ваша запись подтверждена.")
        # notify admins about comment
        if ADMIN_IDS:
            for admin_id in ADMIN_IDS:
                try:
                    await bot.send_message(admin_id, f"💬 Комментарий к записи от {message.from_user.first_name}: {message.text.strip()}")
                except:
                    pass
    except Exception as e:
        print(f"Error in handle_comment: {e}")
        await message.reply("❌ Ошибка при сохранении комментария")


@dp.message(Command("skip"))
async def skip_comment(message: types.Message):
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute(
                "SELECT id FROM bookings WHERE user_id = ? AND comment IS NULL ORDER BY id DESC LIMIT 1",
                (message.from_user.id,)
            )
            row = await cursor.fetchone()
            if not row:
                await message.reply("Нет ожидающих комментариев.")
                return

            booking_id = row[0]
            await db.execute("UPDATE bookings SET comment = ? WHERE id = ?", ("", booking_id))
            await db.commit()

        await message.reply("Комментарий пропущен. Ваша запись подтверждена.")
    except Exception as e:
        print(f"Error in skip_comment: {e}")
        await message.reply("❌ Ошибка")

async def main():
    await init_db()
    
    # Delete any existing webhook to use polling instead
    try:
        await bot.delete_webhook(drop_pending_updates=True)
    except Exception as e:
        print(f"Webhook cleanup: {e}")
    
    # print bot identity to verify which bot is running
    try:
        me = await bot.get_me()
        print(f"Bot identity: {me.username} ({me.id})")
    except Exception as e:
        print(f"Could not fetch bot identity: {e}")

    print("✅ Bot started")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n❌ Bot stopped")
    except Exception as e:
        print(f"❌ Fatal error: {e}")
