from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from aiogram.filters import Command
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import requests, asyncio
from datetime import datetime, timedelta
from config import BOT_TOKEN, OPENWEATHER_API_KEY, CHAT_ID, CITY, WEATHER_HOUR, WEATHER_MINUTE, SEND_CAT_IMAGE, CAT_DIR
import os
from pathlib import Path
from ICON_EMOJI import ICON_EMOJI
from aiogram.types import FSInputFile

bot = Bot(BOT_TOKEN)
dp = Dispatcher()  # в v3 Bot передавать не нужно
scheduler = AsyncIOScheduler(timezone="Europe/Moscow")


# ---- helpers for cat images ----
_BASE_DIR = Path(__file__).parent
CAT_DIR_PATH = _BASE_DIR / CAT_DIR
CAT_INDEX_FILE = _BASE_DIR / ".cat_index"
FACTS_FILE = _BASE_DIR / "facts.txt"
FACT_INDEX_FILE = _BASE_DIR / ".fact_index"

def _list_cat_images():
    """Return list of image filenames in CAT_DIR sorted by their leading integer (e.g. 1.webp, 2.png)."""
    if not CAT_DIR_PATH.exists():
        return []
    items = []
    for p in CAT_DIR_PATH.iterdir():
        if not p.is_file():
            continue
        stem = p.stem
        try:
            num = int(stem)
        except Exception:
            continue
        items.append((num, p.name))
    items.sort()
    return [name for num, name in items]

def get_next_cat_image_path():
    """Return absolute path to next cat image and advance the index (cyclic).

    Uses a small file `.cat_index` in the project root to remember the next requested number.
    """
    images = _list_cat_images()
    if not images:
        return None

    # Build map of available numeric names
    image_map = {int(Path(n).stem): n for n in images}
    nums = sorted(image_map.keys())

    # Read current index (desired starting number)
    try:
        idx = int(CAT_INDEX_FILE.read_text().strip())
    except Exception:
        idx = nums[0]

    # Choose smallest available number >= idx, otherwise wrap to first
    chosen = None
    for n in nums:
        if n >= idx:
            chosen = n
            break
    if chosen is None:
        chosen = nums[0]

    # Compute next index (cyclic through available numbers)
    pos = nums.index(chosen)
    next_pos = (pos + 1) % len(nums)
    next_idx = nums[next_pos]

    # Persist next index
    try:
        CAT_INDEX_FILE.write_text(str(next_idx))
    except Exception as e:
        print("Не удалось обновить индекс картинки cat:", e)

    return str(CAT_DIR_PATH / image_map[chosen])


def _load_facts():
    """Load non-empty lines from facts.txt preserving order."""
    if not FACTS_FILE.exists():
        return []
    try:
        lines = [line.strip() for line in FACTS_FILE.read_text(encoding='utf-8').splitlines()]
        return [l for l in lines if l]
    except Exception as e:
        print("Не удалось прочитать facts.txt:", e)
        return []


def get_next_fact():
    """Return next fact (string) from facts.txt in order, cyclically advancing index in .fact_index."""
    facts = _load_facts()
    if not facts:
        return None

    try:
        idx = int(FACT_INDEX_FILE.read_text().strip())
    except Exception:
        idx = 0

    if idx < 0 or idx >= len(facts):
        idx = 0

    fact = facts[idx]
    next_idx = (idx + 1) % len(facts)
    try:
        FACT_INDEX_FILE.write_text(str(next_idx))
    except Exception as e:
        print("Не удалось обновить индекс facts:", e)

    return fact


def classify_pressure(pressure_hpa: int) -> str:
    """Классификация атмосферного давления для человека.

    Возвращаемые метки:
      - "Очень низкое"
      - "Пониженное"
      - "Норма"
      - "Повышенное"
      - "Очень высокое"

    Пороговые значения ориентировочные (в hPa). При необходимости можно скорректировать.
    """
    try:
        p = int(pressure_hpa)
    except Exception:
        return "Неизвестно"

    # Пороговые значения (ориентировочно):
    if p < 990:
        return "Очень низкое"
    if 990 <= p <= 1005:
        return "Пониженное"
    if 1006 <= p <= 1020:
        return "Нормальное"
    if 1021 <= p <= 1030:
        return "Повышенное"
    return "Очень высокое"


def classify_wind(speed_ms: float) -> str:
    """Классификация силы ветра в метрах в секунду.

    Возвращаемые метки (ориентировочно):
      - "Штиль"
      - "Лёгкий ветерок"
      - "Слабый ветер"
      - "Умеренный ветер"
      - "Сильный ветер"
      - "Очень сильный ветер"
      - "Штормовой"

    Пороговые значения (м/с) по вашей шкале:
      0–1      -> Штиль
      1–3      -> Лёгкий ветерок
      4–6      -> Слабый ветер
      7–10     -> Умеренный ветер
      11–15    -> Сильный ветер
      16–20    -> Очень сильный ветер
      >20      -> Штормовой
    Используем последовательное сравнение (<=), чтобы не было перекрытий.
    """
    try:
        v = float(speed_ms)
    except Exception:
        return "Неизвестно"

    # Применяем указанные пороги. Границы реализованы как <= верхней границы:
    if v <= 1.0:
        return "Штиль"
    if v <= 3.0:
        return "Лёгкий ветерок"
    if v <= 6.0:
        return "Слабый ветер"
    if v <= 10.0:
        return "Умеренный ветер"
    if v <= 15.0:
        return "Сильный ветер"
    if v <= 20.0:
        return "Очень сильный ветер"
    return "Штормовой"


# ==== Получение полной погоды с прогнозом на 13:00 и 19:00 ====
def get_full_weather():
    # Текущая погода
    url_now = f"https://api.openweathermap.org/data/2.5/weather?q={CITY}&appid={OPENWEATHER_API_KEY}&units=metric&lang=ru"
    now = requests.get(url_now).json()

    icon_now = now["weather"][0]["icon"]
    emoji_now = ICON_EMOJI.get(icon_now, "")
    weather_now = f"{now['weather'][0]['description']} {emoji_now}"

    temp_now = round(now["main"]["temp"])
    feels_now = round(now["main"]["feels_like"])
    temp_min = round(now["main"]["temp_min"])
    temp_max = round(now["main"]["temp_max"])
    humidity = now["main"]["humidity"]
    pressure = now["main"]["pressure"]
    wind_speed = now["wind"]["speed"]
    wind_deg = now["wind"]["deg"]
    gust = now["wind"].get("gust", 0)
    clouds = now["clouds"]["all"]
    rain = now.get("rain", {}).get("1h", 0)
    snow = now.get("snow", {}).get("1h", 0)
    # Корректируем время рассвета/заката на +2 часа (например, поправка часового пояса)
    sunrise = (datetime.fromtimestamp(now["sys"]["sunrise"]) + timedelta(hours=2)).strftime("%H:%M")
    sunset = (datetime.fromtimestamp(now["sys"]["sunset"]) + timedelta(hours=2)).strftime("%H:%M")

    # Прогноз
    url_forecast = f"https://api.openweathermap.org/data/2.5/forecast?q={CITY}&appid={OPENWEATHER_API_KEY}&units=metric&lang=ru"
    forecast = requests.get(url_forecast).json()

    today = datetime.now().date()
    forecast_hours = [12, 18]  # Часы, к которым нужен прогноз
    forecast_texts = []

    for target_hour in forecast_hours:
        # Ищем прогноз строго на target_hour (только записи той же даты с точным часом)
        candidates = [
            item for item in forecast["list"]
            if datetime.fromisoformat(item["dt_txt"]).date() == today
            and int(item["dt_txt"][11:13]) == target_hour
        ]
        closest_item = candidates[0] if candidates else None
        if closest_item:
            temp = round(closest_item["main"]["temp"])
            feels = round(closest_item["main"]["feels_like"])
            icon_fc = closest_item["weather"][0]["icon"]
            emoji_fc = ICON_EMOJI.get(icon_fc, "")
            weather_desc = f"{closest_item['weather'][0]['description'].capitalize()} {emoji_fc}"
            wind_speed_fc = closest_item["wind"]["speed"]
            wind_deg_fc = closest_item["wind"]["deg"]
            humidity_fc = closest_item["main"]["humidity"]
            pop = int(closest_item.get("pop", 0) * 100)

            forecast_texts.append(
                f"{target_hour:02d}:00:\n"
                f"{weather_desc}\n"
                f"{temp:+}°C, ощущается как {feels:+}°C\n"
                f"{classify_wind(wind_speed_fc)} {wind_speed_fc}м/с\n"
                f"Вероятность осадков: {pop}%\n"
            )

    # Добавляем в начало заголовок с днём недели и датой (две первые строки)
    weekday_names = [
        "Понедельник", "Вторник", "Среда", "Четверг",
        "Пятница", "Суббота", "Воскресенье"
    ]
    month_names = [
        "января", "февраля", "марта", "апреля", "мая", "июня",
        "июля", "августа", "сентября", "октября", "ноября", "декабря"
    ]
    now_dt = datetime.now()
    weekday = weekday_names[now_dt.weekday()]
    date_line = f"{now_dt.day} {month_names[now_dt.month - 1]} {now_dt.year}"
    weather_line = f"{weather_now}"
    header = f"{date_line}\n{weekday} - {weather_line}\n\n"

    pressure_label = classify_pressure(pressure)

    message = header + (
        f"{temp_now:+}°C, ощущается {feels_now:+}°C\n"
        f"{pressure_label} давление {pressure}hPa\n"
        f"{classify_wind(wind_speed)} {wind_speed} м/с\n"
        f"{humidity}% влажность\n"
        f"Дождь {rain} мм | Снег {snow} мм\n"
        f"{pop}% вероятность осадков\n\n"
        
        f"Рассвет: {sunrise} ☀️\n"
        f"Закат: {sunset} 🌤\n\n"
    )
    message += "\n".join(forecast_texts)

    # Добавляем в последней строке факт из facts.txt (по порядку)
    try:
        fact = get_next_fact()
        if fact:
            # добавляем как последнюю строку, с одной пустой строкой перед фактом
            message = message.rstrip() + "\n\n" + fact
    except Exception as e:
        print("Ошибка при получении факта:", e)

    return message

# ==== Автоматическая рассылка ====
async def send_weather():
    message = get_full_weather()
    # If enabled and images available, send photo with caption (message)
    if SEND_CAT_IMAGE:
        try:
            img_path = get_next_cat_image_path()
            if img_path and Path(img_path).exists():
                # send as photo with caption using FSInputFile
                await bot.send_photo(CHAT_ID, photo=FSInputFile(img_path), caption=message)
                return
        except Exception as e:
            # log and fallback to text message
            print("Ошибка при отправке картинки из cat:", e)

    await bot.send_message(CHAT_ID, message)

# ==== Обработчик команды /start ====
@dp.message(Command("start"))
async def start_message(message: types.Message):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Отправить прогноз в канал", callback_data="send_channel")]
        ]
    )
    await message.answer("Нажми кнопку, чтобы отправить прогноз погоды в канал:", reply_markup=keyboard)

# ==== Обработчик кнопки ====
@dp.callback_query(lambda c: c.data == "send_channel")
async def callback_send_channel(callback_query: CallbackQuery):
    await send_weather()
    await callback_query.answer("Прогноз отправлен в канал!")

# ==== Запуск бота ====
async def main():
    scheduler.add_job(send_weather, "cron", hour=WEATHER_HOUR, minute=WEATHER_MINUTE)
    scheduler.start()
    print("Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
