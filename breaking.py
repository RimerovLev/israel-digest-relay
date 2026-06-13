import anthropic
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

SYSTEM_PROMPT = """Ты — дежурный редактор экстренного выпуска для русскоязычной аудитории в Израиле.

Задача: проверить источники и ответить ТОЛЬКО одним из двух вариантов:
- Если есть срочная новость: вернуть текст поста
- Если срочного нет: вернуть ровно одно слово "ТИХО"

ПОИСК (используй web_search):
- "Israel breaking news [дата]"
- "Израиль срочно [дата]"
- "сирена тревога Израиль сейчас"
- "major outage down [дата]"

КРИТЕРИИ СРОЧНОСТИ — публиковать ТОЛЬКО если событие ПРЯМО СЕЙЧАС влияет на безопасность, свободу передвижения или финансы жителя и требует действий в ближайший час:

✅ УГРОЗА ЖИЗНИ: сирены в крупных городах (Тель-Авив, Иерусалим, Хайфа, Ашдод, Ашкелон), теракт с жертвами, массовая эвакуация, химическая угроза
✅ ТРАНСПОРТНЫЙ КОЛЛАПС: закрытие Бен-Гуриона, КПП, массовая отмена поездов
✅ ПОЛИТИКА/ВОЕННЫЕ: объявление ЧП или войны, приказ о мобилизации, закрытие школ
✅ ЭКОНОМИКА: курс шекеля изменился 5%+ за час, банки недоступны несколько часов
✅ TECH: глобальный сбой WhatsApp/Telegram/Facebook 30+ минут, сбой Visa/Mastercard глобально

❌ НЕ ПУБЛИКОВАТЬ: заявления политиков, "источники сообщают" без 2 подтверждений, законопроекты, ДТП, спорт, рутинные операции, мелкие tech-сбои

ТРЕБОВАНИЯ К ПУБЛИКАЦИИ:
- Минимум 2 независимых подтверждения (или 1 официальный источник: ЦАХАЛ, полиция, Минздрав)
- Событие произошло в последние 60 минут
- Не повторять то что уже было опубликовано (список в запросе пользователя)

ФОРМАТ ПОСТА (500-1000 знаков, только если есть срочное):
⚠️ СРОЧНО | [HH:MM]

<b>[Одно предложение — что, где, когда]</b>

Известно на данный момент:
• [факт 1]
• [факт 2]
• [что пока неизвестно]

Источник: [название]

[Одна строка — что делать читателю]

ГОЛОС: спокойный, точный. Только подтверждённые факты. Никакой паники."""

def load_sent_history():
    try:
        with open('sent_breaking.json', 'r') as f:
            data = json.load(f)
            # Keep only last 24h
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
    client = anthropic.Anthropic(api_key=os.environ['ANTHROPIC_API_KEY'])

    recent = [h['headline'] for h in sent_history] if sent_history else []
    recent_str = "\n".join(f"- {h}" for h in recent) if recent else "Ничего не было опубликовано за последние 24 часа."

    user_message = f"""Сейчас {now_str} по израильскому времени, {date_str}.

Уже опубликованные срочные новости за последние 24 часа (НЕ повторять):
{recent_str}

Проверь источники. Есть ли что-то срочное за последние 60 минут?
Если да — верни текст поста.
Если нет — верни одно слово: ТИХО"""

    messages = [{"role": "user", "content": user_message}]

    for attempt in range(15):
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1500,
            system=SYSTEM_PROMPT,
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}],
            messages=messages
        )

        print(f"  Attempt {attempt+1}: stop_reason={response.stop_reason}")

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
                        "content": "Search executed."
                    })
            if tool_results:
                messages.append({"role": "user", "content": tool_results})
        else:
            break

    return "ТИХО"

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

def git_commit_history():
    subprocess.run(['git', 'config', 'user.email', 'bot@digest.local'], check=True)
    subprocess.run(['git', 'config', 'user.name', 'DigestBot'], check=True)
    subprocess.run(['git', 'add', 'sent_breaking.json'], check=True)
    subprocess.run(['git', 'commit', '-m', 'Update breaking news history'], check=True)
    subprocess.run(['git', 'push'], check=True)

def main():
    now = get_israel_time()

    # Only run between 06:00 and 23:00 Israel time
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

    print(f"BREAKING NEWS DETECTED:\n{result[:200]}...")

    ok = send_telegram(result, os.environ['TELEGRAM_BOT_TOKEN'], os.environ['TELEGRAM_CHAT_ID'])
    if ok:
        print("✓ Sent to Telegram!")
        # Extract first line as headline for dedup
        headline = result.split('\n')[0][:100]
        save_sent_history(sent_history, headline)
        try:
            git_commit_history()
        except Exception as e:
            print(f"Warning: could not commit history: {e}")
    else:
        print("✗ Telegram send failed")

if __name__ == '__main__':
    main()
