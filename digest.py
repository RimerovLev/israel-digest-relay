from openai import OpenAI
import os
import urllib.request
import urllib.parse
import json
from datetime import datetime, timezone, timedelta


def get_israel_time():
    utc_now = datetime.now(timezone.utc)
    month = utc_now.month
    offset = 3 if 3 < month < 11 or (month == 3 and utc_now.day >= 25) or (month == 10 and utc_now.day < 27) else 2
    return utc_now + timedelta(hours=offset), offset


def determine_digest_type(hour):
    if 4 <= hour < 10:
        return "УТРЕННИЙ", "☀️"
    elif 10 <= hour < 16:
        return "ДНЕВНОЙ", "🌤"
    else:
        return "ВЕЧЕРНИЙ", "🌙"


SYSTEM_PROMPT = """Ты — редактор новостного дайджеста для русскоязычной аудитории в Израиле.
Канал выходит в Telegram три раза в день: утро (07:00), день (12:00), вечер (18:00).

ИСТОЧНИКИ — ищи во всех через web_search:
🇮🇱 На русском: mignews.com, 9tv.co.il, detaly.co.il, newsru.co.il, isra.com, vesty.co.il, cursorinfo.co.il
🇮🇱 На английском: timesofisrael.com, haaretz.com, jpost.com, ynetnews.com, i24news.tv
🌍 Международный контекст: reuters.com, bbc.com/news/world/middle-east, apnews.com

Поисковые запросы:
- "Израиль новости [сегодняшняя дата]"
- "Israel news today"
- "Middle East news today"

АЛГОРИТМ:
1. Сделай 3-4 поисковых запроса чтобы найти 15-20 свежих новостей
2. Сгруппируй по темам: Безопасность/армия, Политика, Экономика, Международный контекст, Жизнь в стране
3. Выбери 4-5 самых значимых из разных групп
4. Напиши дайджест

ФИЛЬТР:
✅ Влияет на жизнь русскоязычного жителя
✅ Свежее — не старше 6 часов
✅ Полная картина — не только одна тема
❌ Светская хроника, спорт без резонанса

☀️ УТРЕННИЙ — тон бодрый, чёткий. Вводная фраза с характером (не "доброе утро"). 4-5 новостей с заголовком и 3-4 предложениями каждая. Закрывающая фраза с иронией или теплом.

🌤 ДНЕВНОЙ — тон деловой. Вводная фраза без воды. 4-5 новостей. Итоговая строка: за чем следить до вечера.

🌙 ВЕЧЕРНИЙ — тон глубже, с позицией. Вводная фраза — настрой на итог. 4-5 новостей, каждая с позицией/выводом. Вопрос к читателям. Подпись канала.

ГОЛОС: друг который объясняет, не диктор. Позиция есть, без агрессии. Ирония — да, паника — нет. Абзацы короткие.

ОБЪЁМ: 2000-2500 знаков.

ВАЖНО: Используй только HTML-форматирование: <b>жирный</b>, <i>курсив</i>. Никаких звёздочек и markdown."""


def generate_digest(digest_type, emoji, now_str, date_str):
    client = OpenAI(api_key=os.environ['OPENAI_API_KEY'])

    user_message = (
        f"Сейчас {now_str} по израильскому времени, {date_str}.\n"
        f"Сгенерируй {digest_type} дайджест {emoji}.\n"
        "Используй web_search для поиска актуальных новостей.\n"
        "Верни только текст для Telegram-канала (без блока Facebook и без заголовка '📱 TELEGRAM:')."
    )

    response = client.responses.create(
        model="gpt-4o",
        instructions=SYSTEM_PROMPT,
        tools=[{"type": "web_search_preview"}],
        input=user_message,
    )

    for item in response.output:
        if item.type == "message":
            for content in item.content:
                if content.type == "output_text" and content.text.strip():
                    return content.text.strip()

    return None


def send_telegram(text, bot_token, chat_id):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    data = urllib.parse.urlencode({
        'chat_id': chat_id,
        'text': text,
        'parse_mode': 'HTML'
    }).encode()
    req = urllib.request.Request(url, data=data, method='POST')
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read().decode())
    return result.get('ok', False)


def main():
    now, _ = get_israel_time()
    digest_type, emoji = determine_digest_type(now.hour)
    now_str = now.strftime('%H:%M')
    date_str = now.strftime('%d.%m.%Y')

    print(f"Generating {emoji} {digest_type} digest for {now_str} Israel time...")

    text = generate_digest(digest_type, emoji, now_str, date_str)
    if not text:
        print("ERROR: Failed to generate digest")
        exit(1)

    print(f"\nGenerated ({len(text)} chars):\n{text[:300]}...\n")

    ok = send_telegram(text, os.environ['TELEGRAM_BOT_TOKEN'], os.environ['TELEGRAM_CHAT_ID'])
    if ok:
        print("✓ Sent to Telegram!")
    else:
        print("✗ Telegram send failed")
        exit(1)


if __name__ == '__main__':
    main()
