#!/usr/bin/env python3
import requests, json, os, re, sys, time, base64
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
        return event_url, event_id
    log("목록 직접 매칭 실패, 개별 이벤트 페이지 확인 중...")
    all_ids = list(dict.fromkeys(re.findall(r'href="/News/Event/(?:Ongoing/)?(\d+)"', html)))
    for event_id in all_ids[:20]:
        event_url = f'https://maplestory.nexon.com/News/Event/{event_id}'
        try:
            detail_html = fetch_html(event_url)
            if sunday_str in detail_html and '썬데이' in detail_html and '메이플' in detail_html:
                log(f"개별 페이지에서 발견: {event_url}")
                return event_url, event_id
        except Exception as e:
            log(f"  {event_id} 확인 오류: {e}")
    return None, None

def get_event_image_url(event_url):
    html = fetch_html(event_url)
    imgs = re.findall(r'https://lwi\.nexon\.com/maplestory/\S+?\.(?:png|jpg|jpeg)', html, re.IGNORECASE)
    board_imgs = [img for img in imgs if 'board' in img.lower()]
    return board_imgs[0] if board_imgs else (imgs[0] if imgs else None)

def get_event_summary(image_url):
    """Gemini Vision API로 이벤트 이미지 분석해서 핵심 혜택 요약 (무료 티어)"""
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=os.environ['GEMINI_API_KEY'], http_options={'api_version': 'v1'})

        # 이미지 다운로드
        headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://maplestory.nexon.com/'}
        resp = requests.get(image_url, headers=headers, timeout=20)
        resp.raise_for_status()

        # 확장자로 미디어 타입 결정
        if image_url.lower().endswith('.jpg') or image_url.lower().endswith('.jpeg'):
            mime_type = 'image/jpeg'
        else:
            mime_type = 'image/png'

        response = client.models.generate_content(
            model='gemini-1.5-flash',
            contents=[
                types.Part.from_bytes(data=resp.content, mime_type=mime_type),
                '이 메이플스토리 썬데이 메이플 이벤트 이미지의 핵심 혜택만 2~3줄 요약. 불렛포인트(•) 사용. 80자 이내.'
            ],
            config=types.GenerateContentConfig(max_output_tokens=150)
        )
        summary = response.text.strip()
        log(f"이미지 분석 완료: {summary}")
        return summary
    except Exception as e:
        log(f"이미지 분석 실패 (요약 생략): {e}")
        return None

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

def build_message(sunday_str, event_url, summary=None):
    sunday_short = sunday_str[5:]  # '07.05'
    parts = [f"🍁 썬데이 메이플 ({sunday_short})"]
    if summary:
        parts.append(summary)
    parts.append(f"링크: {event_url}")
    msg = "\n".join(parts)
    return msg[:200] if len(msg) > 200 else msg

def main():
    sunday_str = get_this_sunday_str()
    log(f"이번 주 일요일: {sunday_str}")
    for attempt in range(1, MAX_RETRIES + 1):
        log(f"시도 {attempt}/{MAX_RETRIES} - {datetime.now(KST).strftime('%H:%M')}")
        try:
            event_url, event_id = find_sunday_maple_event(sunday_str)
        except Exception as e:
            log(f"오류: {e}")
            event_url = None
        if event_url:
            log(f"이벤트 발견! {event_url}")
            image_url = get_event_image_url(event_url)

            # Gemini Vision으로 이미지 요약
            summary = None
            if image_url and os.environ.get('GEMINI_API_KEY'):
                summary = get_event_summary(image_url)

            message = build_message(sunday_str, event_url, summary)
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
