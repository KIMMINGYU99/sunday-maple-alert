#!/usr/bin/env python3
import requests, json, os, re, sys, time
from datetime import datetime, timedelta
import pytz

KST = pytz.timezone('Asia/Seoul')
RETRY_INTERVAL_SEC = 2 * 60 * 60  # 2ìê°
MAX_RETRIES = 8                     # ìµë 8í (16ìê°)

def log(msg):
    print(msg, flush=True)

def get_this_sunday_str():
    now = datetime.now(KST)
    days_until_sunday = (6 - now.weekday()) % 7
    if days_until_sunday == 0:
        days_until_sunday = 7
    return (now + timedelta(days=days_until_sunday)).strftime('%Y.%m.%d')

def fetch_html(url):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    return resp.text

def find_sunday_maple_event(sunday_str):
    html = fetch_html('https://maplestory.nexon.com/News/Event')
    pattern = r'<dt>\s*<a href="/News/Event/(?:Ongoing/)?(\d+)"[^>]*>([^<]*(?:ì¬ë°ì´[^<]*ë©ì´í|ë©ì´í[^<]*ì¬ë°ì´)[^<]*)</a>'
    matches = re.findall(pattern, html, re.IGNORECASE | re.DOTALL)
    if matches:
        event_id, title = matches[0]
        event_url = f'https://maplestory.nexon.com/News/Event/{event_id}'
        log(f"ëª©ë¡ìì ë°ê²¬: {title.strip()} -> {event_url}")
        return event_url, title.strip()
    log("ëª©ë¡ ì§ì  ë§¤ì¹­ ì¤í¨, ê°ë³ ì´ë²¤í¸ íì´ì§ íì¸ ì¤...")
    all_ids = list(dict.fromkeys(re.findall(r'href="/News/Event/(?:Ongoing/)?(\d+)"', html)))
    for event_id in all_ids[:20]:
        event_url = f'https://maplestory.nexon.com/News/Event/{event_id}'
        try:
            detail_html = fetch_html(event_url)
            if sunday_str in detail_html and 'ì¬ë°ì´' in detail_html and 'ë©ì´í' in detail_html:
                log(f"ê°ë³ íì´ì§ìì ë°ê²¬: {event_url}")
                return event_url, 'ì¬ë°ì´ ë©ì´í'
        except Exception as e:
            log(f"  {event_id} íì¸ ì¤ë¥: {e}")
    return None, None

GENERIC_TITLES = {'ì´ë²¤í¸', 'ë´ì¤', 'ì´ë²¤í¸ | ë´ì¤', 'ì´ë²¤í¸|ë´ì¤', 'ê³µì§ì¬í­', 'ìë°ì´í¸'}

def get_event_detail(event_url):
    html = fetch_html(event_url)
    title = None

    # 1ìì: <dt><a href="...">ì ëª©</a> - ëª©ë¡/ìì¸ íì´ì§ ê³µíµì¼ë¡ ìë ì¤ì  ì ëª©
    dt_match = re.search(r'<dt>\s*<a[^>]+>([^<]+)</a>', html)
    if dt_match:
        raw = dt_match.group(1).strip()
        if raw and raw not in GENERIC_TITLES and len(raw) > 2:
            title = raw
            log(f"dt íê·¸ìì ì ëª© ì¶ì¶: {title}")

    # 2ìì: og:title (ìì± ìì ë ê°ì§)
    if not title:
        og = re.search(r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"', html)
        if not og:
            og = re.search(r'<meta[^>]+content="([^"]+)"[^>]+property="og:title"', html)
        if og:
            raw = re.sub(r'\s*\|\s*ë©ì´íì¤í ë¦¬.*$', '', og.group(1)).strip()
            raw = re.sub(r'^.*?ì¬ë°ì´\s*ë©ì´í\s*[-â]\s*', '', raw).strip()
            if raw and raw not in GENERIC_TITLES:
                title = raw

    # 3ìì: <title> íê·¸ (ì ë¤ë¦­ ì ëª© ì ì¸)
    if not title:
        pt = re.search(r'<title>([^<]+)</title>', html)
        if pt:
            raw = re.sub(r'\s*\|\s*ë©ì´íì¤í ë¦¬.*$', '', pt.group(1)).strip()
            raw = re.sub(r'^.*?ì¬ë°ì´\s*ë©ì´í\s*[-â]\s*', '', raw).strip()
            if raw and raw not in GENERIC_TITLES:
                title = raw

    # ì´ë¯¸ì§ URL ì¶ì¶
    imgs = re.findall(r'https://lwi\.nexon\.com/maplestory/\S+?\.(?:png|jpg|jpeg)', html, re.IGNORECASE)
    board_imgs = [img for img in imgs if 'board' in img.lower()]
    image_url = board_imgs[0] if board_imgs else (imgs[0] if imgs else None)
    return title, image_url

def get_kakao_access_token():
    data = {
        'grant_type': 'refresh_token',
        'client_id': os.environ['KAKAO_REST_API_KEY'],
        'refresh_token': os.environ['KAKAO_REFRESH_TOKEN'],
    }
    if os.environ.get('KAKAO_CLIENT_SECRET'):
        data['client_secret'] = os.environ['KAKAO_CLIENT_SECRET']
    resp = requests.post('https://kauth.kakao.com/oauth/token', data=data, timeout=10)
    result = resp.json()
    if 'error' in result:
        raise RuntimeError(f"ì¹´ì¹´ì¤ í í° ë°ê¸ ì¤í¨: {result}")
    return result['access_token']

def send_kakao_message(access_token, text):
    template = {
        "object_type": "text",
        "text": text,
        "link": {"web_url": "https://maplestory.nexon.com/News/Event",
                 "mobile_web_url": "https://maplestory.nexon.com/News/Event"}
    }
    resp = requests.post(
        'https://kapi.kakao.com/v2/api/talk/memo/default/send',
        headers={'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/x-www-form-urlencoded'},
        data={'template_object': json.dumps(template, ensure_ascii=False)},
        timeout=10)
    result = resp.json()
    if result.get('result_code') != 0:
        raise RuntimeError(f"ì¹´ì¹´ì¤í¡ ë©ìì§ ì ì¡ ì¤í¨: {result}")
    log("ì¹´ì¹´ì¤í¡ ì ì¡ ìë£!")

def build_message(sunday_str, title, event_url, image_url):
    sunday_short = sunday_str[5:]
    parts = [
        f"📌 {title or '썬데이 메이플'}",
        f"📅 날짜: {sunday_short} (일)",
        f"🖼 이미지: {image_url or '(이미지 없음)'}",
        f"🔗 공지: {event_url}",
    ]
    msg = "\n".join(parts)
    return msg[:400] if len(msg) > 400 else msg

def main():
    sunday_str = get_this_sunday_str()
    log(f"ì´ë² ì£¼ ì¼ìì¼: {sunday_str}")
    for attempt in range(1, MAX_RETRIES + 1):
        log(f"ìë {attempt}/{MAX_RETRIES} - {datetime.now(KST).strftime('%H:%M')}")
        try:
            event_url, title = find_sunday_maple_event(sunday_str)
        except Exception as e:
            log(f"ì¤ë¥: {e}")
            event_url = None
        if event_url:
            log(f"ì´ë²¤í¸ ë°ê²¬! {event_url}")
            detail_title, image_url = get_event_detail(event_url)
            event_title = detail_title if detail_title else title
            log(f"ì´ë²¤í¸ ì ëª©: {event_title}")
            log(f"ì´ë¯¸ì§ URL: {image_url}")
            message = build_message(sunday_str, event_title, event_url, image_url)
            log(f"ì ì¡ ë©ìì§:\n{message}")
            access_token = get_kakao_access_token()
            send_kakao_message(access_token, message)
            return
        log("ìì§ ì¬ë°ì´ ë©ì´í ì ë³´ê° ììµëë¤.")
        if attempt < MAX_RETRIES:
            log(f"{RETRY_INTERVAL_SEC // 3600}ìê° í ì¬ìë...")
            time.sleep(RETRY_INTERVAL_SEC)
    log("ìµë ì¬ìë ì´ê³¼.")
    sys.exit(1)

if __name__ == '__main__':
    main()
