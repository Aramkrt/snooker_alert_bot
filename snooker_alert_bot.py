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

# === Парсер даты из расписания с учётом сезона ===
def parse_schedule_date(date_str, season_start_year=2025, season_end_year=2026):
    from datetime import datetime
    try:
        dt = datetime.strptime(date_str.strip(), "%d %b")
    except Exception:
        return None

    month = dt.month
    # Предполагаем сезон с июня (6) по май (5) следующего года
    if month >= 6:
        year = season_start_year
    else:
        year = season_end_year

    return dt.replace(year=year).date()

# === Получение расписания турниров с датами в формате date ===
def get_schedule():
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
            return [], "Не удалось найти таблицу турниров."

        rows = target_table.find_all('tr')[1:]
        results = []
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

                start_date = parse_schedule_date(start_str)
                finish_date = parse_schedule_date(finish_str)

                tournaments.append({
                    "start": start_date,
                    "finish": finish_date,
                    "name": tournament,
                    "venue": venue,
                    "winner": winner,
                    "runner_up": runner_up,
                    "score": score,
                })

                results.append(
                    f"📅 {start_str} — {finish_str}\n"
                    f"🏆 {tournament}\n"
                    f"📍 {venue}\n"
                    f"🥇 Победитель: {winner}\n"
                    f"🥈 Финалист: {runner_up}\n"
                    f"⚔️ Счёт финала: {score}"
                )

        if not results:
            return [], "Нет данных о турнирах."

        return tournaments, "\n\n".join(results)
    except Exception as e:
        return [], f"Ошибка при получении расписания: {e}"

# === Уведомления: ближайший турнир и турнир, стартующий завтра ===
def get_upcoming_tournament_from_schedule():
    tournaments, _ = get_schedule()
    if not tournaments:
        return "Не удалось получить данные о турнирах для уведомления."

    today = datetime.now(LOCAL_TZ).date()
    tomorrow = today + timedelta(days=1)

    tournaments_sorted = sorted([t for t in tournaments if t['start'] is not None], key=lambda x: x['start'])

    # Турнир, который стартует завтра
    for t in tournaments_sorted:
        if t['start'] == tomorrow:
            return f"🎱 Завтра стартует чемпионат:\n🏆 {t['name']}\n📅 {t['start'].strftime('%d %B %Y')}"

    # Если нет турнира завтра, ближайший будущий турнир
    future_tournaments = [t for t in tournaments_sorted if t['start'] > today]
    if not future_tournaments:
        return "Пока нет запланированных турниров."
    next_tournament = future_tournaments[0]
    days_left = (next_tournament['start'] - today).days
    return f"До следующего чемпионата «{next_tournament['name']}» осталось {days_left} дней.\nДата начала: {next_tournament['start'].strftime('%d %B %Y')}"

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
    tournaments, data = get_schedule()
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
        text = get_upcoming_tournament_from_schedule()
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

    # Запуск ежедневного задания в 21:00 по LOCAL_TZ (Москва)
    app.job_queue.run_daily(daily_notification, time=dt_time(21, 0, tzinfo=LOCAL_TZ))

    app.run_polling()
