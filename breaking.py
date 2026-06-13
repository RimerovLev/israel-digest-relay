from openai import OpenAI
import os, json, urllib.request, urllib.parse, base64
from datetime import datetime, timezone, timedelta

REPO = 'RimerovLev/israel-digest-relay'
HISTORY_FILE = 'sent_breaking.json'

def get_israel_time():
    utc_now = datetime.now(timezone.utc)
    m = utc_now.month
    offset = 3 if (3 < m < 11 or (m==3 and utc_now.day>=25) or (m==10 and utc_now.day<27)) else 2
    return utc_now + timedelta(hours=offset)

def gh_api(path, method='GET', body=None):
    token = os.environ['GH_TOKEN']
    url = f'https://api.github.com/repos/{REPO}/contents/{path}'
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method,
        headers={'Authorization': f'token {token}', 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        print(f'GitHub API error: {e}')
        return {}

def load_sent_history():
    r = gh_api(HISTORY_FILE)
    if 'content' not in r:
        return [], None
    content = base64.b64decode(r['content']).decode()
    data = json.loads(content)
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    return [h for h in data if h.get('time','') > cutoff], r['sha']

def save_sent_history(history, sha, new_headline):
    history.append({'time': datetime.now(timezone.utc).isoformat(), 'headline': new_headline})
    history = history[-50:]
    content = base64.b64encode(json.dumps(history, ensure_ascii=False, indent=2).encode()).decode()
    body = {'message': 'Update breaking news history', 'content': content}
    if sha:
        body['sha'] = sha
    gh_api(HISTORY_FILE, method='PUT', body=body)

SYSTEM_PROMPT = (
    "You are an emergency news editor for Russian-speaking audience in Israel. "
    "Search for breaking news using web_search. "
    "Return ONLY one of: post text in Russian (500-1000 chars) OR single word ТИХО. "
    "Publish ONLY: air sirens in major cities, terror attacks with casualties, "
    "airport/railway closure, declaration of emergency/war, shekel +-5% in 1h, "
    "global WhatsApp/Telegram outage 30+ min. "
    "Require 2 confirmations or 1 official source (IDF/police/Health Ministry). "
    "Event must be in last 60 minutes. Do NOT repeat already published items. "
    "Format if breaking: WARNING URGENT | HH:MM\n<b>What where when</b>\nKnown:\n- fact1\n- fact2\nSource: name\nAction for reader."
)

def check_breaking(now_str, date_str, sent_history):
    client = OpenAI(api_key=os.environ['OPENAI_API_KEY'])
    recent = ', '.join(h['headline'] for h in sent_history) or 'nothing in last 24h'
    msg = f"Time: {now_str} Israel, {date_str}. Already sent (skip): {recent}. Check for breaking news in last 60 min."
    response = client.responses.create(
        model='gpt-4o-mini',
        instructions=SYSTEM_PROMPT,
        tools=[{'type': 'web_search_preview'}],
        input=msg,
    )
    for item in response.output:
        if item.type == 'message':
            for c in item.content:
                if c.type == 'output_text' and c.text.strip():
                    return c.text.strip()
    return 'ТИХО'

def send_telegram(text):
    url = f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/sendMessage"
    data = urllib.parse.urlencode({'chat_id': os.environ['TELEGRAM_CHAT_ID'], 'text': text, 'parse_mode': 'HTML'}).encode()
    req = urllib.request.Request(url, data=data, method='POST')
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode()).get('ok', False)

def main():
    now = get_israel_time()
    if not (6 <= now.hour < 23):
        print(f"Outside active hours ({now.strftime('%H:%M')}). Skipping."); return
    print(f"Breaking check at {now.strftime('%H:%M')} Israel time...")
    history, sha = load_sent_history()
    result = check_breaking(now.strftime('%H:%M'), now.strftime('%d.%m.%Y'), history)
    if result.strip().upper() == 'ТИХО' or len(result.strip()) < 20:
        print("Silent."); return
    print(f"BREAKING: {result[:150]}")
    if send_telegram(result):
        print("Sent!")
        save_sent_history(history, sha, result.split('\n')[0][:100])
    else:
        print("Send failed")

if __name__ == '__main__':
    main()
