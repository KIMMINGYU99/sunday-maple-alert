#!/usr/bin/env python3
import requests, json, os, re, sys, time
from datetime import datetime, timedelta
import pytz

KST = pytz.timezone('Asia/Seoul')
RETRY_INTERVAL_SEC = 2 * 60 * 60  # 2시간
MAX_RETRIES = 8                     # 최대 8회 (16시간)

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
    blocks = re.findall(
        r'href="(https://maplestory\.nexon\.com/News/Event/(\d+))".*?썬데이\s*메이플.*?(\d{4}\.\d{2}\.\d{2})',
        html, re.DOTALL)
    for event_url, event_id, date_str in blocks:
        if date_str == sunday_str:
            return event_url, event_id
    recent = re.findall(r'href="(https://maplestory\.nexon\.com/News/Event/(\d+))".*?썬데이\s*메이플', html, re.DOTALL)
    if recent:
        event_url, event_id = recent[0]
        if sunday_str in fetch_html(event_url):
            return event_url, event_id
    return None, None

def get_event_image_url(event_url):
    html = fetch_html(event_url)
    imgs = re.findall(r'https://lwi\.nexon\.com/maplestory/[^"\'>\s]+\.png', html)
    board_imgs = [img for img in imgs if 'board' in img]
    return board_imgs[0] if board_imgs else (imgs[0] if imgs else None)

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
    print("카카오톡 전송 완료!")

def build_message(sunday_str, event_url, image_url):
    sunday_short = sunday_str[5:]
    parts = [f"선데이 메이플 ({sunday_short})"]
    if image_url:
        parts.append(f"\n이미지: {image_url}")
    parts.append(f"\n링크: {event_url}")
    msg = "\n".join(parts)
    return msg[:200] if len(msg) > 200 else msg

def main():
    sunday_str = get_this_sunday_str()
    print(f"이번 주 일요일: {sunday_str}")
    for attempt in range(1, MAX_RETRIES + 1):
        print(f"\n시도 {attempt}/{MAX_RETRIES} - {datetime.now(KST).strftime('%H:%M')}")
        try:
            event_url, event_id = find_sunday_maple_event(sunday_str)
        except Exception as e:
            print(f"오류: {e}")
            event_url = None
        if event_url:
            print(f"이벤트 발견! {event_url}")
            image_url = get_event_image_url(event_url)
            message = build_message(sunday_str, event_url, image_url)
            print(f"\n전송 메시지:\n{message}\n")
            access_token = get_kakao_access_token()
            send_kakao_message(access_token, message)
            return
        print("아직 선데이 메이플 정보가 없습니다.")
        if attempt < MAX_RETRIES:
            print(f"{RETRY_INTERVAL_SEC // 3600}시간 후 재시도...")
            time.sleep(RETRY_INTERVAL_SEC)
    print("최대 재시도 초과.")
    sys.exit(1)

if __name__ == '__main__':
    main()
