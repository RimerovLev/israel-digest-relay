from openai import OpenAI
import os
import json
import urllib.request
import urllib.parse
import subprocess
from datetime import datetime, timezone, timedelta


def get_israel_time():
    utc_now = datetime.now(timezone.utc)
    month = utc_now.month
    day = utc_now.day
    offset = 3 if (3 < month < 11 or (month == 3 and day >= 25) or (month == 10 and day < 27)) else 2
    return utc_now + timedelta(hours=offset)


SYSTEM_PROMPT = """Ты - дежурный редактор экстренного выпуска для русскоязычной аудитории в Израиле.

Задача: проверить источники и ответить ТОЛЬКО одним из двух вариантов:
- Если есть срочная новость: вернуть текст поста
- Если срочного нет: вернуть ровно одно слово ТИХО

ПОИСК (используй web_search):
- Israel breaking news сегодня
- Израиль срочно сегодня
- сирена тревога Израиль сейчас

КРИТЕРИИ СРОЧНОСТИ:
Сирены в крупных городах, теракт с жертвами, массовая эвакуация
Закрытие Бен-Гуриона, КПП, массовая отмена поездов
Объявление ЧП или войны, приказ о мобилизации
Курс шекеля изменился на 5%+ за час
Глобальный сбой WhatsApp/Telegram 30+ минут

НЕ ПУБЛИКОВАТЬ: заявления политиков, ДТП, спорт, рутинные операции

ТРЕБОВАНИЯ:
Минимум 2 подтверждения или 1 официальный источник ЦАХАЛ/полиция/Минздрав
Событие в последние 60 минут
Не повторять уже опубликованное

ФОРМАТ если есть срочное:
СРОЧНО HH:MM
Что где когда
Известно:
факт 1
факт 2
Источник: название
Что делать читателю

ГОЛОС: спокойный, точный, только факты."""


def load_sent_history():
    try:
        with open('sent_breaking.json', 'r') as f:
            data = json.load(f)
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        return [h for h in data if h.get('time', '') > cutoff]
    except:
        return []


def save_sent_history(history, new_headline):
    history.append({'time': datetime.now(timezone.utc).isoformat(), 'headline': new_headline})
    history = history[-50:]
    with open('sent_breaking.json', 'w') as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def check_breaking_news(now_str, date_str, sent_history):
    client = OpenAI(api_key=os.environ['OPENAI_API_KEY'])
    recent = [h['headline'] for h in sent_history] if sent_history else []
    recent_str = ", ".join(recent) if recent else "nothing published in last 24h"
    user_message = (
        f"Time: {now_str} Israel time, {date_str}. "
        f"Already published (do not repeat): {recent_str}. "
        "Check sources. Any breaking news in last 60 minutes? "
        "If yes - return post text in Russian. If no - return single word: ТИХО"
    )
    response = client.responses.create(
        model="gpt-4o-mini",
        instructions=SYSTEM_PROMPT,
        tools=[{"type": "web_search_preview"}],
        input=user_message,
    )
    for item in response.output:
        if item.type == "message":
            for content in item.content:
                if content.type == "output_text" and content.text.strip():
                    return content.text.strip()
    return "ТИХО"


def send_telegram(text, bot_token, chat_id):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    data = urllib.parse.urlencode({'chat_id': chat_id, 'text': text, 'parse_mode': 'HTML'}).encode()
    req = urllib.request.Request(url, data=data, method='POST')
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode()).get('ok', False)


def git_commit_history():
    subprocess.run(['git', 'config', 'user.email', 'bot@digest.local'], check=True)
    subprocess.run(['git', 'config', 'user.name', 'DigestBot'], check=True)
    subprocess.run(['git', 'add', 'sent_breaking.json'], check=True)
    subprocess.run(['git', 'commit', '-m', 'Update breaking news history'], check=True)
    subprocess.run(['git', 'push'], check=True)


def main():
    now = get_israel_time()
    if not (6 <= now.hour < 23):
        print(f"Outside active hours ({now.strftime('%H:%M')} Israel time). Skipping.")
        return
    now_str = now.strftime('%H:%M')
    date_str = now.strftime('%d.%m.%Y')
    print(f"Breaking news check at {now_str} Israel time...")
    sent_history = load_sent_history()
    result = check_breaking_news(now_str, date_str, sent_history)
    if result.strip().upper() == "ТИХО" or len(result.strip()) < 20:
        print("No breaking news. Silent.")
        return
    print(f"BREAKING NEWS DETECTED: {result[:200]}")
    ok = send_telegram(result, os.environ['TELEGRAM_BOT_TOKEN'], os.environ['TELEGRAM_CHAT_ID'])
    if ok:
        print("Sent to Telegram!")
        save_sent_history(sent_history, result.split('\n')[0][:100])
        try:
            git_commit_history()
        except Exception as e:
            print(f"Warning: could not commit history: {e}")
    else:
        print("Telegram send failed")


if __name__ == '__main__':
    main()
