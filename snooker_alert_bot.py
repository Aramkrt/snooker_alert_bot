import logging
import asyncio
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta, time as dt_time
import pytz
import json
import os
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from telegram import Update, ReplyKeyboardMarkup
import sys

print("Python version:", sys.version)

# === Конфигурация ===
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OWNER_CHAT_ID = 734782204
SUBSCRIBERS_FILE = 'subscribers.json'
LOCAL_TZ = pytz.timezone("Europe/Moscow")  # часовой пояс
CURRENT_YEAR = 2025  # Год для парсинга дат из расписания (можно менять)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# === Подписчики ===
def load_subscribers():
    if os.path.exists(SUBSCRIBERS_FILE):
        with open(SUBSCRIBERS_FILE, 'r', encoding='utf-8') as f:
            return set(json.load(f))
    return set()

def save_subscribers(subscribers):
    with open(SUBSCRIBERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(list(subscribers), f)

# === Парсинг дат ===
def parse_date(date_str):
    """Парсинг даты даже если диапазон."""
    try:
        date_str = date_str.split("–")[0].split("-")[0].strip()
        return datetime.strptime(date_str, "%d %B %Y").date()
    except Exception:
        try:
            dt = datetime.strptime(date_str, "%B %Y")
            return dt.replace(day=1).date()
        except Exception:
            return None

def parse_start_finish_date(date_str):
    """
    Парсит дату формата '30 Mar' или '5 Apr' в объект date с годом CURRENT_YEAR.
    """
    try:
        dt = datetime.strptime(f"{date_str} {CURRENT_YEAR}", "%d %b %Y")
        return dt.date()
    except Exception:
        return None

# === Получение информации о турнирах ===
def get_tournaments():
    try:
        url = "https://en.wikipedia.org/wiki/2025%E2%80%9326_snooker_season"
        response = requests.get(url)
        soup = BeautifulSoup(response.text, 'html.parser')
        tables = soup.find_all('table', {'class': 'wikitable'})
        target_table = None
        for table in tables:
            header = table.find('tr')
            headers = [th.get_text(strip=True) for th in header.find_all(['th', 'td'])]
            if {'Start', 'Finish', 'Tournament'}.issubset(set(headers)):
                target_table = table
                break

        if not target_table:
            return []

        rows = target_table.find_all('tr')[1:]
        tournaments = []
        for row in rows:
            cols = row.find_all('td')
            if len(cols) >= 3:
                start_date = parse_date(cols[0].get_text(strip=True))
                finish_date = parse_date(cols[1].get_text(strip=True))
                tournament_name = cols[2].get_text(strip=True)
                if start_date:
                    tournaments.append({
                        'start': start_date,
                        'finish': finish_date,
                        'name': tournament_name
                    })
        return tournaments
    except Exception as e:
        logging.error(f"Ошибка парсинга турниров: {e}")
        return []

# === Получение расписания турниров (возвращает строку) ===
def get_schedule():
    try:
        tournaments = get_schedule_tournaments()
        if not tournaments:
            return "Нет данных о турнирах."

        results = []
        for t in tournaments:
            results.append(
                f"📅 {t['start_str']} — {t['finish_str']}\n"
                f"🏆 {t['tournament']}\n"
                f"📍 {t['venue']}\n"
                f"🥇 Победитель: {t['winner']}\n"
                f"🥈 Финалист: {t['runner_up']}\n"
                f"⚔️ Счёт финала: {t['score']}"
            )
        return "\n\n".join(results)
    except Exception as e:
        return f"Ошибка при получении расписания: {e}"

# === Получение турниров с объектами date (для поиска ближайшего) ===
def get_schedule_tournaments():
    try:
        url = "https://en.wikipedia.org/wiki/2025%E2%80%9326_snooker_season"
        response = requests.get(url)
        soup = BeautifulSoup(response.text, 'html.parser')
        tables = soup.find_all('table', {'class': 'wikitable'})
        target_table = None
        for table in tables:
            header = table.find('tr')
            headers = [th.get_text(strip=True) for th in header.find_all(['th', 'td'])]
            if {'Start', 'Finish', 'Tournament', 'Venue', 'Winner', 'Runner-up', 'Score'}.issubset(set(headers)):
                target_table = table
                break

        if not target_table:
            return []

        rows = target_table.find_all('tr')[1:]
        tournaments = []
        for row in rows:
            cols = row.find_all('td')
            if len(cols) >= 7:
                start_str = cols[0].get_text(strip=True)
                finish_str = cols[1].get_text(strip=True)
                tournament = cols[2].get_text(strip=True)
                venue = cols[3].get_text(separator=" ", strip=True)
                winner = cols[4].get_text(strip=True)
                score = cols[5].get_text(strip=True)
                runner_up = cols[6].get_text(strip=True)

                start_date = parse_start_finish_date(start_str)
                finish_date = parse_start_finish_date(finish_str)

                if start_date is None:
                    continue

                tournaments.append({
                    'start': start_date,
                    'finish': finish_date,
                    'tournament': tournament,
                    'venue': venue,
                    'winner': winner,
                    'runner_up': runner_up,
                    'score': score,
                    'start_str': start_str,
                    'finish_str': finish_str,
                })

        tournaments.sort(key=lambda x: x['start'])

        # --- Ролл списка, чтобы сезон начинался с июня ---
        june_index = None
        for i, t in enumerate(tournaments):
            if t['start'].month >= 6:
                june_index = i
                break

        if june_index is not None and june_index > 0:
            tournaments = tournaments[june_index:] + tournaments[:june_index]

        return tournaments
    except Exception as e:
        logging.error(f"Ошибка в get_schedule_tournaments: {e}")
        return []

# === Получение ближайшего турнира для уведомлений ===
def get_upcoming_tournament_tomorrow():
    try:
        tournaments = get_schedule_tournaments()
        if not tournaments:
            return None

        tomorrow = datetime.now(LOCAL_TZ).date() + timedelta(days=1)
        for t in tournaments:
            if t['start'] == tomorrow:
                return f"🎱 Завтра стартует чемпионат:\n🏆 {t['tournament']}\n📅 {t['start'].strftime('%d %B %Y')}"

        today = datetime.now(LOCAL_TZ).date()
        future = [t for t in tournaments if t['start'] > today]
        if future:
            next_t = future[0]
            days_left = (next_t['start'] - today).days
            return f"До следующего чемпионата «{next_t['tournament']}» осталось {days_left} дней.\nДата начала: {next_t['start'].strftime('%d %B %Y')}"

        return None
    except Exception as e:
        logging.error(f"Ошибка в get_upcoming_tournament_tomorrow: {e}")
        return None

# === Получение рейтинга ===
def get_world_ranking():
    try:
        url = "https://en.wikipedia.org/wiki/Snooker_world_rankings"
        response = requests.get(url)
        soup = BeautifulSoup(response.text, 'html.parser')
        tables = soup.find_all('table', {'class': 'wikitable'})
        ranking_table = None
        for table in tables:
            headers = [th.text.strip() for th in table.find_all('th')]
            if 'Points' in headers and 'Player' in headers:
                ranking_table = table
                break

        if not ranking_table:
            return "Не удалось найти таблицу рейтинга."

        rows = ranking_table.find_all('tr')[1:]
        results = []
        for row in rows:
            cols = row.find_all(['td', 'th'])
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
    keyboard = [
        ["/Подписаться", "/Отписаться"],
        ["/Расписание сезона", "/Рейтинг снукеристов"],
        ["/блмжайщий турнир"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)
    await update.message.reply_text("📋 что интересует?", reply_markup=reply_markup)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_chat.id)
    subscribers = load_subscribers()
    message_text = ("⏰ Уведомления о турнирах будут приходить за день до начала, в 21:00 по GMT+3 (московскому времени)\n\n")
    if user_id not in subscribers:
        subscribers.add(user_id)
        save_subscribers(subscribers)
        await update.message.reply_text("✅ Ты подписан на уведомления о снукере.\n\n" + message_text)
    else:
        await update.message.reply_text("✅ Ты уже подписан.\n\n" + message_text)
    await send_commands_menu(update)

async def unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_chat.id)
    subscribers = load_subscribers()
    if user_id in subscribers:
        subscribers.remove(user_id)
        save_subscribers(subscribers)
        await update.message.reply_text("✅ Ты отписан от уведомлений о снукере.")
    else:
        await update.message.reply_text("⚠️ Ты не был подписан.")
    await send_commands_menu(update)

async def schedule_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Получаю расписание чемпионатов текущего сезона...")
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

    with open('user_replies.txt', 'a', encoding='utf-8') as f:
        f.write(f"{user_id} ({user_name}): {text}\n")

    await context.bot.send_message(
        chat_id=OWNER_CHAT_ID,
        text=f"Ответ от {user_name} (id: {user_id}):\n{text}"
    )

    await update.message.reply_text("мы все учтем, спасибо!")
    await send_commands_menu(update)

# === Новая команда "Следующий чемпионат" ===
async def next_tournament_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tournaments = get_schedule_tournaments()
    if not tournaments:
        await update.message.reply_text("Не удалось получить данные о турнирах.")
        return

    today = datetime.now(LOCAL_TZ).date()
    future_tournaments = [t for t in tournaments if t['start'] >= today]
    if not future_tournaments:
        await update.message.reply_text("Ближайших турниров не найдено.")
        return

    next_t = future_tournaments[0]
    days_left = (next_t['start'] - today).days
    msg = (
        f"🎱 Следующий чемпионат:\n"
        f"🏆 {next_t['tournament']}\n"
        f"📅 Начинается: {next_t['start'].strftime('%d %B %Y')}\n"
        f"⏳ Осталось дней: {days_left}"
    )
    await update.message.reply_text(msg)
    await send_commands_menu(update)

# === Ежедневная задача уведомления ===
async def daily_notification(context: ContextTypes.DEFAULT_TYPE):
    try:
        text = get_upcoming_tournament_tomorrow()
        if not text:
            text = "Пока нет ближайших турниров."

        subscribers = load_subscribers()
        for chat_id in subscribers:
            try:
                await context.bot.send_message(chat_id=chat_id, text=text)
                logging.info(f"Отправлено уведомление {chat_id}")
            except Exception as e:
                logging.warning(f"Ошибка отправки {chat_id}: {e}")
    except Exception as e:
        logging.error(f"Ошибка в daily_notification: {e}")

# === Запуск бота ===
if __name__ == '__main__':
    import nest_asyncio
    nest_asyncio.apply()

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("Подписаться", start))
    app.add_handler(CommandHandler("Отписаться", unsubscribe))
    app.add_handler(CommandHandler("Расписание сезона", schedule_command))
    app.add_handler(CommandHandler("Рейтинг снукеристов", ranking_command))
    app.add_handler(CommandHandler("блмжайщий турнир", next_tournament_command))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), message_handler))

    # Запуск ежедневного задания в 21:00 по Москве
    app.job_queue.run_daily(daily_notification, time=dt_time(21, 0, tzinfo=LOCAL_TZ))

    app.run_polling()
