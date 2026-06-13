import anthropic
import os
import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta

# Israel timezone: UTC+3 in summer, UTC+2 in winter (DST approximation)
def get_israel_time():
    utc_now = datetime.now(timezone.utc)
    # DST: last Sunday March to last Sunday October = UTC+3, else UTC+2
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

☀️ УТРЕННИЙ — тон бодрый, чёткий. Вводная фраза с характером (не "доброе утро"). 4-5 новостей с заголовком и 3-4 предложениями каждая. Погода в конце: "☀️ Тель-Авив +28° | Иерусалим +24°". Закрывающая фраза с иронией или теплом.

🌤 ДНЕВНОЙ — тон деловой. Вводная фраза без воды. 4-5 новостей. Итоговая строка: за чем следить до вечера.

🌙 ВЕЧЕРНИЙ — тон глубже, с позицией. Вводная фраза — настрой на итог. 4-5 новостей, каждая с позицией/выводом. Вопрос к читателям. Подпись канала.

ГОЛОС: друг который объясняет, не диктор. Позиция есть, без агрессии. Ирония — да, паника — нет. Абзацы короткие.

ОБЪЁМ: 2000-2500 знаков.

ВАЖНО: Используй только HTML-форматирование: <b>жирный</b>, <i>курсив</i>. Никаких звёздочек и markdown."""

def generate_digest(digest_type, emoji, now_str, date_str):
    client = anthropic.Anthropic(api_key=os.environ['ANTHROPIC_API_KEY'])

    user_message = f"""Сейчас {now_str} по израильскому времени, {date_str}.
Сгенерируй {digest_type} дайджест {emoji}.
Используй web_search для поиска актуальных новостей.
Верни только текст для Telegram-канала (без блока Facebook и без заголовка "📱 TELEGRAM:")."""

    messages = [{"role": "user", "content": user_message}]

    for attempt in range(15):
        response = client.messages.create(
            model="claude-opus-4-8",
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 8}],
            messages=messages
        )

        print(f"  Iteration {attempt+1}: stop_reason={response.stop_reason}, blocks={[b.type for b in response.content]}")

        if response.stop_reason == "end_turn":
            for block in response.content:
                if hasattr(block, 'text') and block.text.strip():
                    return block.text.strip()
            break

        elif response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": response.content})
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": "Search executed by Anthropic servers."
                    })
            if tool_results:
                messages.append({"role": "user", "content": tool_results})
        else:
            break

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
