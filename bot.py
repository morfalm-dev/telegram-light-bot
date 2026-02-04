import asyncio
import os
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup

from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.client.default import DefaultBotProperties

# ================== CONFIG ==================

TOKEN = os.getenv("BOT_TOKEN")  # Railway ENV
URL = "https://www.poe.pl.ua/disconnection/power-outages/"
SUB_LINK = "https://t.me/+35STqXwHpOVhNGNi"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept-Language": "uk-UA,uk;q=0.9,en;q=0.8",
}

# ================== KEYBOARD ==================

keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="📅 Сьогодні"),
            KeyboardButton(text="📅 Завтра")
        ]
    ],
    resize_keyboard=True
)

# ================== HELPERS ==================

def add_30min(t):
    h, m = t
    m += 30
    if m == 60:
        h += 1
        m = 0
    if h == 24:
        h = 0
    return h, m


def halfhour_to_ranges(halfhours):
    if not halfhours:
        return []

    halfhours = sorted(set(halfhours))
    ranges = []

    start = prev = halfhours[0]

    for h in halfhours[1:]:
        if (
            (h[0] == prev[0] and h[1] == prev[1] + 30) or
            (h[0] == prev[0] + 1 and h[1] == 0 and prev[1] == 30)
        ):
            prev = h
        else:
            ranges.append((start, add_30min(prev)))
            start = prev = h

    ranges.append((start, add_30min(prev)))
    return ranges

# ================== PARSER ==================

def parse_tables():
    response = requests.get(URL, headers=HEADERS, timeout=30)

    if response.status_code != 200:
        raise RuntimeError(f"HTTP {response.status_code}")

    soup = BeautifulSoup(response.text, "html.parser")

    tables = soup.find_all("table", class_="turnoff-scheduleui-table")
    if not tables:
        raise RuntimeError("Tables not found")

    return tables


def parse_table(table):
    schedule = {}
    rows = table.find("tbody").find_all("tr")
    current_queue = None

    for row in rows:
        cells = row.find_all("td")
        if not cells:
            continue

        first_classes = cells[0].get("class", [])

        if "turnoff-scheduleui-table-queue" in first_classes:
            current_queue = cells[0].get_text(strip=True)
            subqueue = cells[1].get_text(strip=True)
            lights = cells[2:]
        else:
            subqueue = cells[0].get_text(strip=True)
            lights = cells[1:]

        key = f"{current_queue}, {subqueue}"
        schedule[key] = []

        for i, cell in enumerate(lights):
            classes = cell.get("class", [])
            hour = i // 2
            minute = 30 if i % 2 else 0

            if "light_2" in classes or "light_3" in classes:
                schedule[key].append((hour, minute))

    return schedule

# ================== FORMAT ==================

def format_message(schedule, date: datetime, is_today: bool):
    date_str = date.strftime("%d-%m-%Y")
    now = datetime.now()
    now_minutes = now.hour * 60 + now.minute

    msg = (
        "⚠️ <b>УВАГА! ОНОВЛЕННЯ ГРАФІКУ!</b>\n\n"
        f"🟥🟨🟩 <b>ГРАФІК ВІДКЛЮЧЕНЬ СВІТЛА "
        f"{'НА ' + date_str if is_today else 'НА ЗАВТРА, ' + date_str}:</b>\n\n"
    )

    for key, halfhours in schedule.items():
        ranges = []

        for start, end in halfhour_to_ranges(halfhours):
            if is_today:
                end_min = end[0] * 60 + end[1]
                if end == (0, 0):
                    end_min = 1440
                if end_min <= now_minutes:
                    continue
            ranges.append((start, end))

        if not ranges:
            continue

        msg += f"🔹 <b>{key} підчерга:</b>\n"
        for start, end in ranges:
            msg += f"{start[0]:02d}:{start[1]:02d} - {end[0]:02d}:{end[1]:02d}\n"
        msg += "\n"

    msg += f"🔸 <a href=\"{SUB_LINK}\">Підписатися на графік відключень</a>"
    return msg

# ================== BOT ==================

async def main():
    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher()

    @dp.message(Command("start"))
    async def start_cmd(message: Message):
        await message.answer("Обери день для перегляду графіку ⬇️", reply_markup=keyboard)

    async def handle(message: Message, day: str):
        await message.answer("⏳ Отримую графік...")

        try:
            tables = await asyncio.to_thread(parse_tables)
        except Exception as e:
            await message.answer(f"❌ Помилка отримання даних:\n{e}")
            return

        if day == "today":
            schedule = parse_table(tables[0])
            msg = format_message(schedule, datetime.now(), True)
        else:
            if len(tables) < 2:
                await message.answer("ℹ️ Графік на завтра ще не опубліковано")
                return
            schedule = parse_table(tables[1])
            msg = format_message(
                schedule,
                datetime.now() + timedelta(days=1),
                False
            )

        await message.answer(msg, reply_markup=keyboard)

    @dp.message(lambda m: m.text == "📅 Сьогодні")
    async def today_btn(message: Message):
        await handle(message, "today")

    @dp.message(lambda m: m.text == "📅 Завтра")
    async def tomorrow_btn(message: Message):
        await handle(message, "tomorrow")

    await dp.start_polling(bot)

# ================== RUN ==================

if __name__ == "__main__":
    asyncio.run(main())
