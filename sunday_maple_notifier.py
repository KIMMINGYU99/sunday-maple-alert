#!/usr/bin/env python3
import requests, json, os, re, sys, time
from datetime import datetime, timedelta
import pytz

KST = pytz.timezone('Asia/Seoul')
RETRY_INTERVAL_SEC = 2 * 60 * 60  # 2시간
MAX_RETRIES = 8                     # 최대 8회 (16시간)

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
    pattern = r'<dt>\s*<a href="/News/Event/(?:Ongoing/)?(\d+)"[^>]*>([^<]*(?:썬데이[^<]*메이플|메이플[^<]*썬데이)[^<]*)</a>'
    matches = re.findall(pattern, html, re.IGNORECASE | re.DOTALL)
    if matches:
        event_id, title = matches[0]
        event_url = f'https://maplestory.nexon.com/News/Event/{event_id}'
        log(f"목록에서 발견: {title.strip()} -> {event_url}")
        return event_url, title.strip()
    log("목록 직접 매칭 실패, 개별 이벤트 페이지 확인 중...")
    all_ids = list(dict.fromkeys(re.findall(r'href="/News/Event/(?:Ongoing/)?(\d+)"', html)))
    for event_id in all_ids[:20]:
        event_url = f'https://maplestory.nexon.com/News/Event/{event_id}'
        try:
            detail_html = fetch_html(event_url)
            if sunday_str in detail_html and '썬데이' in detail_html and '메이플' in detail_html:
                log(f"개별 페이지에서 발견: {event_url}")
                return event_url, '썬데이 메이플'
        except Exception as e:
            log(f"  {event_id} 확인 오류: {e}")
    return None, None

def get_event_detail(event_url):
    html = fetch_html(event_url)
    title = None
    og_title = re.search(r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"', html)
    if not og_title:
        og_title = re.search(r'<meta[^>]+content="([^"]+)"[^>]+property="og:title"', html)
    if og_title:
        raw = og_title.group(1).strip()
        raw = re.sub(r'\s*\|\s*메이플스토리.*$', '', raw).strip()
        raw = re.sub(r'^.*?썬데이\s*메이플\s*[-–]\s*', '', raw).strip()
        if raw:
            title = raw
    if not title:
        page_title = re.search(r'<title>([^<]+)</title>', html)
        if page_title:
            raw = page_title.group(1).strip()
            raw = re.sub(r'\s*\|\s*메이플스토리.*$', '', raw).strip()
            raw = re.sub(r'^.*?썬데이\s*메이플\s*[-–]\s*', '', raw).strip()
            if raw:
                title = raw
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
        raise RuntimeError(f"카카오 토큰 발급 실패: {result}")
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
        raise RuntimeError(f"카카오톡 메시지 전송 실패: {result}")
    log("카카오톡 전송 완료!")

def build_message(sunday_str, title, event_url, image_url):
    sunday_short = sunday_str[5:]
    parts = [
        f"🍁 썬데이 메이플 ({sunday_short})",
        f"📌 {title}",
        f"🖼 이미지: {image_url}" if image_url else "",
        f"🔗 공지: {event_url}",
    ]
    msg = "\n".join(p for p in parts if p)
    return msg[:400] if len(msg) > 400 else msg

def main():
    sunday_str = get_this_sunday_str()
    log(f"이번 주 일요일: {sunday_str}")
    for attempt in range(1, MAX_RETRIES + 1):
        log(f"시도 {attempt}/{MAX_RETRIES} - {datetime.now(KST).strftime('%H:%M')}")
        try:
            event_url, title = find_sunday_maple_event(sunday_str)
        except Exception as e:
            log(f"오류: {e}")
            event_url = None
        if event_url:
            log(f"이벤트 발견! {event_url}")
            detail_title, image_url = get_event_detail(event_url)
            event_title = detail_title if detail_title else title
            log(f"이벤트 제목: {event_title}")
            log(f"이미지 URL: {image_url}")
            message = build_message(sunday_str, event_title, event_url, image_url)
            log(f"전송 메시지:\n{message}")
            access_token = get_kakao_access_token()
            send_kakao_message(access_token, message)
            return
        log("아직 썬데이 메이플 정보가 없습니다.")
        if attempt < MAX_RETRIES:
            log(f"{RETRY_INTERVAL_SEC // 3600}시간 후 재시도...")
            time.sleep(RETRY_INTERVAL_SEC)
    log("최대 재시도 초과.")
    sys.exit(1)

if __name__ == '__main__':
    main()
