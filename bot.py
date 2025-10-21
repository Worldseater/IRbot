from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from aiogram.filters import Command
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import requests, asyncio
from datetime import datetime
from config import BOT_TOKEN, OPENWEATHER_API_KEY, CHAT_ID, CITY, WEATHER_HOUR, WEATHER_MINUTE
from ICON_EMOJI import ICON_EMOJI

bot = Bot(BOT_TOKEN)
dp = Dispatcher()  # в v3 Bot передавать не нужно
scheduler = AsyncIOScheduler(timezone="Europe/Moscow")

# ==== Получение полной погоды с прогнозом на 13:00 и 19:00 ====
def get_full_weather():
    # Текущая погода
    url_now = f"https://api.openweathermap.org/data/2.5/weather?q={CITY}&appid={OPENWEATHER_API_KEY}&units=metric&lang=ru"
    now = requests.get(url_now).json()

    icon_now = now["weather"][0]["icon"]
    emoji_now = ICON_EMOJI.get(icon_now, "")
    weather_now = f"{now['weather'][0]['description'].capitalize()} {emoji_now}"

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
    sunrise = datetime.fromtimestamp(now["sys"]["sunrise"]).strftime("%H:%M")
    sunset = datetime.fromtimestamp(now["sys"]["sunset"]).strftime("%H:%M")

    # Прогноз
    url_forecast = f"https://api.openweathermap.org/data/2.5/forecast?q={CITY}&appid={OPENWEATHER_API_KEY}&units=metric&lang=ru"
    forecast = requests.get(url_forecast).json()

    today = datetime.now().date()
    forecast_hours = [13, 19]  # Часы, к которым нужен прогноз
    forecast_texts = []

    for target_hour in forecast_hours:
        # Ищем ближайший прогноз к target_hour
        closest_item = min(
            (item for item in forecast["list"] if datetime.fromisoformat(item["dt_txt"]).date() == today),
            key=lambda x: abs(int(x["dt_txt"][11:13]) - target_hour),
            default=None
        )
        if closest_item:
            temp = round(closest_item["main"]["temp"])
            feels = round(closest_item["main"]["feels_like"])
            icon_fc = closest_item["weather"][0]["icon"]
            emoji_fc = ICON_EMOJI.get(icon_fc, "")
            weather_desc = f"{closest_item['weather'][0]['description']} {emoji_fc}"
            wind_speed_fc = closest_item["wind"]["speed"]
            wind_deg_fc = closest_item["wind"]["deg"]
            humidity_fc = closest_item["main"]["humidity"]
            pop = int(closest_item.get("pop", 0) * 100)

            forecast_texts.append(
                f"🌤 Прогноз погоды на {target_hour:02d}:00:\n"
                f"Температура: {temp:+}°C (ощущается как {feels:+}°C)\n"
                f"Погода: {weather_desc}\n"
                f"Ветер: {wind_speed_fc} м/с, {wind_deg_fc}°\n"
                f"Влажность: {humidity_fc}%\n"
                f"Вероятность осадков: {pop}%\n"
            )

    message = (
        f"Город: {CITY}\n\n"
        f"Погода: {weather_now}\n"
        f"Температура: {temp_now:+}°C (ощущается как {feels_now:+}°C)\n"
        f"Минимум/Максимум: {temp_min:+}°C / {temp_max:+}°C\n"
        f"Влажность: {humidity}%\n"
        f"Давление: {pressure} hPa\n"
        f"Ветер: {wind_speed} м/с, направление {wind_deg}° (порывы до {gust} м/с)\n"
        f"Облачность: {clouds}%\n"
        f"Осадки: дождь {rain} мм, снег {snow} мм\n\n"
        f"Рассвет: {sunrise}\n"
        f"Закат: {sunset}\n\n"
    )
    message += "\n".join(forecast_texts)
    return message

# ==== Автоматическая рассылка ====
async def send_weather():
    message = get_full_weather()
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
