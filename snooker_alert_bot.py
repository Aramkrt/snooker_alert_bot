import logging
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta, time
import pytz
import json
import os
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from telegram import Update, ReplyKeyboardMarkup

# === Конфигурация ===
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OWNER_CHAT_ID = 734782204
SUBSCRIBERS_FILE = "subscribers.json"
LOCAL_TZ = pytz.timezone("Europe/Moscow")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)


# === Подписчики ===
def load_subscribers():
    if os.path.exists(SUBSCRIBERS_FILE):
        with open(SUBSCRIBERS_FILE, "r") as f:
            return set(json.load(f))
    return set()


def save_subscribers(subscribers):
    with open(SUBSCRIBERS_FILE, "w") as f:
        json.dump(list(subscribers), f)


# === Парсинг дат ===
def parse_date(date_str):
    try:
        date_str = date_str.split("–")[0].split("-")[0].strip()
        return datetime.strptime(date_str, "%d %B %Y").date()
    except Exception:
        try:
            dt = datetime.strptime(date_str, "%B %Y")
            return dt.replace(day=1).date()
        except Exception:
            return None


# === Получение следующего турнира ===
def get_next_tournament_info():
    try:
        url = "https://en.wikipedia.org/wiki/2025%E2%80%9326_snooker_season"
        response = requests.get(url)
        soup = BeautifulSoup(response.text, "html.parser")

        tables = soup.find_all("table", {"class": "wikitable"})
        target_table = None
        for table in tables:
            header = table.find("tr")
            headers = [th.get_text(strip=True) for th in header.find_all(["th", "td"])]
            if {"Start", "Finish", "Tournament"}.issubset(set(headers)):
                target_table = table
                break

        if not target_table:
            return None, None

        rows = target_table.find_all("tr")[1:]
        today = datetime.now(LOCAL_TZ).date()
        for row in rows:
            cols = row.find_all("td")
            if len(cols) >= 3:
                start_date = parse_date(cols[0].get_text(strip=True))
                if start_date and start_date >= today:
                    tournament = cols[2].get_text(strip=True)
                    return start_date, tournament

        return None, None
    except Exception as e:
        logging.error(f"Ошибка парсинга турнира: {e}")
        return None, None


def get_schedule():
    try:
        url = "https://en.wikipedia.org/wiki/2025%E2%80%9326_snooker_season"
        response = requests.get(url)
        soup = BeautifulSoup(response.text, "html.parser")
        tables = soup.find_all("table", {"class": "wikitable"})
        target_table = None
        for table in tables:
            header = table.find("tr")
            headers = [th.get_text(strip=True) for th in header.find_all(["th", "td"])]
            if {
                "Start",
                "Finish",
                "Tournament",
                "Venue",
                "Winner",
                "Runner-up",
                "Score",
            }.issubset(set(headers)):
                target_table = table
                break

        if not target_table:
            return "Не удалось найти таблицу турниров."

        rows = target_table.find_all("tr")[1:]
        results = []
        for row in rows:
            cols = row.find_all("td")
            if len(cols) >= 7:
                start = cols[0].get_text(strip=True)
                finish = cols[1].get_text(strip=True)
                tournament = cols[2].get_text(strip=True)
                venue = cols[3].get_text(strip=True)
                winner = cols[4].get_text(strip=True)
                runner_up = cols[5].get_text(strip=True)
                score = cols[6].get_text(strip=True)
                results.append(
                    f"📅 {start} — {finish}\n🏆 {tournament}\n📍 {venue}\n🥇 Победитель: {winner}\n🥈 Проигравший: {runner_up}\n⚔️ Счёт: {score}"
                )

        if not results:
            return "Нет данных о турнирах."

        return "\n\n".join(results)
    except Exception as e:
        return f"Ошибка при получении расписания: {e}"


def get_world_ranking():
    try:
        url = "https://en.wikipedia.org/wiki/Snooker_world_rankings"
        response = requests.get(url)
        soup = BeautifulSoup(response.text, "html.parser")
        tables = soup.find_all("table", {"class": "wikitable"})
        ranking_table = None
        for table in tables:
            headers = [th.text.strip() for th in table.find_all("th")]
            if "Points" in headers and "Player" in headers:
                ranking_table = table
                break

        if not ranking_table:
            return "Не удалось найти таблицу рейтинга."

        rows = ranking_table.find_all("tr")[1:]
        results = []
        for row in rows:
            cols = row.find_all(["td", "th"])
            if len(cols) >= 3:
                position = cols[0].text.strip()
                player = cols[1].text.strip()
                points = cols[2].text.strip()
                results.append(f"{position}. {player} — {points} очков")

        if not results:
            return "Рейтинг пуст."

        return "🏆 Мировой рейтинг снукера:\n\n" + "\n".join(results)
    except Exception as e:
        return f"Ошибка при получении рейтинга: {e}"


# === Команды бота ===
async def send_commands_menu(update: Update):
    keyboard = [["/start", "/unsubscribe"], ["/schedule", "/ranking"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("📋 Команды:", reply_markup=reply_markup)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_chat.id)
    subscribers = load_subscribers()
    message_text = (
        "⏰ Уведомления будут приходить каждый день в 21:00 по Москве.\n\n"
    )
    if user_id not in subscribers:
        subscribers.add(user_id)
        save_subscribers(subscribers)
        await update.message.reply_text("✅ Ты подписан на уведомления.\n\n" + message_text)
    else:
        await update.message.reply_text("✅ Ты уже подписан.\n\n" + message_text)
    await send_commands_menu(update)


async def unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_chat.id)
    subscribers = load_subscribers()
    if user_id in subscribers:
        subscribers.remove(user_id)
        save_subscribers(subscribers)
        await update.message.reply_text("✅ Ты отписан.")
    else:
        await update.message.reply_text("⚠️ Ты не был подписан.")
    await send_commands_menu(update)


async def schedule_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Получаю расписание чемпионатов...")
    data = get_schedule()
    if len(data) > 3900:
        data = data[:3900] + "\n\n...и ещё турниры доступны на Википедии."
    await update.message.reply_text(data)
    await send_commands_menu(update)


async def ranking_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Получаю текущий мировой рейтинг...")
    data = get_world_ranking()
    max_len = 4000
    if len(data) <= max_len:
        await update.message.reply_text(data)
    else:
        parts = []
        current = ""
        for line in data.split("\n"):
            if len(current) + len(line) + 1 > max_len:
                parts.append(current)
                current = ""
            current += line + "\n"
        if current:
            parts.append(current)
        for part in parts:
            await update.message.reply_text(part)
    await update.message.reply_text("а сколько твой рейтинг?)")
    await send_commands_menu(update)


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_chat.id)
    user = update.effective_user
    text = update.message.text

    if user.username:
        user_name = f"@{user.username}"
    else:
        user_name = user.first_name or "Unknown"
        if user.last_name:
            user_name += f" {user.last_name}"

    with open("user_replies.txt", "a", encoding="utf-8") as f:
        f.write(f"{user_id} ({user_name}): {text}\n")

    await context.bot.send_message(
        chat_id=OWNER_CHAT_ID, text=f"Ответ от {user_name} (id: {user_id}):\n{text}"
    )

    await update.message.reply_text("мы все учтем, спасибо!")
    await send_commands_menu(update)


# === Планировщик: раз в день в 21:00 по Москве ===
async def daily_check(context: ContextTypes.DEFAULT_TYPE):
    start_date, tournament = get_next_tournament_info()
    today = datetime.now(LOCAL_TZ).date()
    tomorrow = today + timedelta(days=1)

    if start_date is None:
        text = "❌ Не удалось определить дату следующего чемпионата."
    elif start_date == tomorrow:
        text = f"🎱 Завтра стартует чемпионат:\n🏆 {tournament}\n📅 {start_date.strftime('%d %B %Y')}"
    else:
        days_left = (start_date - today).days
        text = (
            f"⏳ До следующего чемпионата «{tournament}» осталось {days_left} дней.\n"
            f"📅 Старт: {start_date.strftime('%d %B %Y')}"
        )

    subscribers = load_subscribers()
    for chat_id in subscribers:
        try:
            await context.bot.send_message(chat_id=chat_id, text=text)
            logging.info(f"Отправлено уведомление {chat_id}")
        except Exception as e:
            logging.warning(f"Ошибка отправки {chat_id}: {e}")


# === Запуск бота ===
if __name__ == "__main__":
    import nest_asyncio

    nest_asyncio.apply()

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("unsubscribe", unsubscribe))
    app.add_handler(CommandHandler("schedule", schedule_command))
    app.add_handler(CommandHandler("ranking", ranking_command))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), message_handler))

    # Планируем задачу на 21:00 по Москве
    app.job_queue.run_daily(daily_check, time=time(21, 0, tzinfo=LOCAL_TZ))

    app.run_polling()
