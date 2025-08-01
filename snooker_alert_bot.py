import logging
import asyncio
import requests
import schedule
from bs4 import BeautifulSoup
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from datetime import datetime, timedelta
import json
import os

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
SUBSCRIBERS_FILE = 'subscribers.json'

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

def load_subscribers():
    if os.path.exists(SUBSCRIBERS_FILE):
        with open(SUBSCRIBERS_FILE, 'r') as f:
            return set(json.load(f))
    return set()

def save_subscribers(subscribers):
    with open(SUBSCRIBERS_FILE, 'w') as f:
        json.dump(list(subscribers), f)

async def send_commands_menu(update: Update):
    keyboard = [
        ["/start", "/unsubscribe"],
        ["/schedule", "/ranking"],
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)
    await update.message.reply_text(" ", reply_markup=reply_markup)

def get_upcoming_tournament_tomorrow():
    try:
        url = "https://en.wikipedia.org/wiki/2025%E2%80%9326_snooker_season"
        response = requests.get(url)
        soup = BeautifulSoup(response.text, 'html.parser')
        tomorrow = datetime.now().date() + timedelta(days=1)

        tables = soup.find_all('table', {'class': 'wikitable'})
        for table in tables:
            headers = [th.get_text(strip=True) for th in table.find('tr').find_all(['th', 'td'])]
            if {'Start', 'Finish', 'Tournament'}.issubset(set(headers)):
                rows = table.find_all('tr')[1:]
                for row in rows:
                    cols = row.find_all('td')
                    if len(cols) >= 3:
                        start_date_str = cols[0].get_text(strip=True)
                        try:
                            start_date = datetime.strptime(start_date_str, "%d %B %Y").date()
                        except:
                            try:
                                start_date = datetime.strptime(start_date_str, "%B %Y").date().replace(day=1)
                            except:
                                continue
                        if start_date == tomorrow:
                            tournament = cols[2].get_text(strip=True)
                            return f"🎱 Завтра стартует чемпионат:\n🏆 {tournament}\n📅 {start_date_str}"
        return None
    except Exception as e:
        return f"Ошибка при проверке турниров: {e}"

def get_schedule():
    try:
        url = "https://en.wikipedia.org/wiki/2025%E2%80%9326_snooker_season"
        response = requests.get(url)
        soup = BeautifulSoup(response.text, 'html.parser')
        tables = soup.find_all('table', {'class': 'wikitable'})

        for table in tables:
            headers = [th.get_text(strip=True) for th in table.find('tr').find_all(['th', 'td'])]
            if {'Start', 'Finish', 'Tournament'}.issubset(set(headers)):
                idx_start = headers.index('Start')
                idx_finish = headers.index('Finish')
                idx_tournament = headers.index('Tournament')
                idx_venue = headers.index('Venue') if 'Venue' in headers else None
                idx_winner = headers.index('Winner') if 'Winner' in headers else None
                idx_runner_up = headers.index('Runner-up') if 'Runner-up' in headers else None
                idx_score = headers.index('Score') if 'Score' in headers else None

                results = []
                for row in table.find_all('tr')[1:]:
                    cols = row.find_all('td')
                    if len(cols) < 3:
                        continue

                    start = cols[idx_start].get_text(strip=True)
                    finish = cols[idx_finish].get_text(strip=True)
                    tournament = cols[idx_tournament].get_text(strip=True)
                    venue = cols[idx_venue].get_text(strip=True) if idx_venue is not None and len(cols) > idx_venue else None
                    winner = cols[idx_winner].get_text(strip=True) if idx_winner is not None and len(cols) > idx_winner else None
                    runner_up = cols[idx_runner_up].get_text(strip=True) if idx_runner_up is not None and len(cols) > idx_runner_up else None
                    score = cols[idx_score].get_text(strip=True) if idx_score is not None and len(cols) > idx_score else None

                    line = f"📅 {start} — {finish}\n🏆 {tournament}"
                    if venue:
                        line += f"\n📍 {venue}"
                    if winner:
                        line += f"\n🥇 {winner}"
                    if runner_up:
                        line += f"\n🥈 {runner_up}"
                    if score:
                        line += f"\n🎯 Счёт: {score}"
                    results.append(line)

                if not results:
                    return "Нет данных о турнирах."
                return "\n\n".join(results)

        return "Не удалось найти таблицу турниров."

    except Exception as e:
        return f"Ошибка при получении расписания: {e}"

def get_world_ranking():
    try:
        url = "https://en.wikipedia.org/wiki/Snooker_world_rankings"
        response = requests.get(url)
        soup = BeautifulSoup(response.text, 'html.parser')
        tables = soup.find_all('table', {'class': 'wikitable'})
        for table in tables:
            headers = [th.get_text(strip=True) for th in table.find_all('th')]
            if 'Points' in headers and 'Player' in headers:
                rows = table.find_all('tr')[1:]
                results = []
                for row in rows:
                    cols = row.find_all(['td', 'th'])
                    if len(cols) >= 3:
                        pos = cols[0].text.strip()
                        player = cols[1].text.strip()
                        points = cols[2].text.strip()
                        results.append(f"{pos}. {player} — {points} очков")
                return "🏆 Мировой рейтинг снукера:\n\n" + "\n".join(results[:50])
        return "Не удалось найти таблицу рейтинга."
    except Exception as e:
        return f"Ошибка при получении рейтинга: {e}"

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

async def scheduled_check(application):
    text = get_upcoming_tournament_tomorrow()
    if not text:
        return
    if text.startswith("Ошибка"):
        logging.warning(text)
        return
    subscribers = load_subscribers()
    for chat_id in subscribers:
        try:
            await application.bot.send_message(chat_id=chat_id, text=text)
            logging.info(f"Отправлено уведомление {chat_id}")
        except Exception as e:
            logging.warning(f"Ошибка отправки {chat_id}: {e}")

async def scheduler(application):
    schedule.every().day.at("21:00").do(lambda: asyncio.create_task(scheduled_check(application)))
    while True:
        schedule.run_pending()
        await asyncio.sleep(60)

async def on_startup(app):
    asyncio.create_task(scheduler(app))

if __name__ == '__main__':
    import nest_asyncio
    nest_asyncio.apply()
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).post_init(on_startup).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("unsubscribe", unsubscribe))
    app.add_handler(CommandHandler("schedule", schedule_command))
    app.add_handler(CommandHandler("ranking", ranking_command))
    app.run_polling()
