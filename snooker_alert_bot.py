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

# === Получение списка турниров с расписанием ===
def get_tournaments_schedule():
    try:
        url = "https://en.wikipedia.org/wiki/2025%E2%80%9326_snooker_season"
        response = requests.get(url)
        soup = BeautifulSoup(response.text, 'html.parser')
        tables = soup.find_all('table', {'class': 'wikitable'})
        target_table = None
        for table in tables:
            header = table.find('tr')
            headers = [th.get_text(strip=True) for th in header.find_all(['th', 'td'])]
            needed_headers = {'Start', 'Finish', 'Tournament', 'Venue', 'Winner', 'Runner-up', 'Score'}
            if needed_headers.issubset(set(headers)):
                target_table = table
                break
        if not target_table:
            return []

        rows = target_table.find_all('tr')[1:]
        tournaments = []
        for row in rows:
            cols = row.find_all('td')
            if len(cols) >= 7:
                start_date = parse_date(cols[0].get_text(strip=True))
                finish_date = parse_date(cols[1].get_text(strip=True))
                tournament_name = cols[2].get_text(strip=True)
                venue = cols[3].get_text(separator=" ", strip=True)
                winner = cols[4].get_text(strip=True)
                score = cols[5].get_text(strip=True)
                runner_up = cols[6].get_text(strip=True)

                tournaments.append({
                    'start': start_date,
                    'finish': finish_date,
                    'name': tournament_name,
                    'venue': venue,
                    'winner': winner,
                    'score': score,
                    'runner_up': runner_up,
                })
        return tournaments
    except Exception as e:
        logging.error(f"Ошибка в get_tournaments_schedule: {e}")
        return []

# === Получение расписания турниров в виде текста для команды /schedule ===
def get_schedule():
    try:
        tournaments = get_tournaments_schedule()
        if not tournaments:
            return "Нет данных о турнирах."
        results = []
        for t in tournaments:
            start = t['start'].strftime('%d %B %Y') if t['start'] else "?"
            finish = t['finish'].strftime('%d %B %Y') if t['finish'] else "?"
            results.append(
                f"📅 {start} — {finish}\n"
                f"🏆 {t['name']}\n"
                f"📍 {t['venue']}\n"
                f"🥇 Победитель: {t['winner']}\n"
                f"🥈 Финалист: {t['runner_up']}\n"
                f"⚔️ Счёт финала: {t['score']}"
            )
        return "\n\n".join(results)
    except Exception as e:
        return f"Ошибка при получении расписания: {e}"

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
        ["/start", "/unsubscribe"],
        ["/schedule", "/ranking"],
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)
    await update.message.reply_text("📋 Команды:", reply_markup=reply_markup)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_chat.id)
    subscribers = load_subscribers()
    message_text = ("⏰ Уведомления о турнирах будут приходить за день до начала, примерно в 21:00.\n\n")
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

    with open('user_replies.txt', 'a', encoding='utf-8') as f:
        f.write(f"{user_id} ({user_name}): {text}\n")

    await context.bot.send_message(
        chat_id=OWNER_CHAT_ID,
        text=f"Ответ от {user_name} (id: {user_id}):\n{text}"
    )

    await update.message.reply_text("мы все учтем, спасибо!")
    await send_commands_menu(update)

# === Ежедневная задача ===
async def daily_notification(context: ContextTypes.DEFAULT_TYPE):
    try:
        tournaments = get_tournaments_schedule()
        if not tournaments:
            text = "Информация о турнирах временно недоступна."
        else:
            today = datetime.now(LOCAL_TZ).date()
            tomorrow = today + timedelta(days=1)
            tomorrow_tournaments = [t for t in tournaments if t['start'] == tomorrow]
            if tomorrow_tournaments:
                t = tomorrow_tournaments[0]
                text = (f"🎱 Завтра стартует чемпионат:\n🏆 {t['name']}\n"
                        f"📅 {t['start'].strftime('%d %B %Y')}\n"
                        f"📍 {t['venue']}")
            else:
                future_tournaments = [t for t in tournaments if t['start'] > today]
                if future_tournaments:
                    next_t = min(future_tournaments, key=lambda x: x['start'])
                    days_left = (next_t['start'] - today).days
                    text = (f"До следующего чемпионата «{next_t['name']}» осталось {days_left} дней.\n"
                            f"Дата начала: {next_t['start'].strftime('%d %B %Y')}\n"
                            f"Место проведения: {next_t['venue']}")
                else:
                    text = "Пока нет запланированных турниров."

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

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("unsubscribe", unsubscribe))
    app.add_handler(CommandHandler("schedule", schedule_command))
    app.add_handler(CommandHandler("ranking", ranking_command))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), message_handler))

    app.job_queue.run_daily(daily_notification, time=dt_time(21, 0, tzinfo=LOCAL_TZ))

    app.run_polling()
