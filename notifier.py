#!/usr/bin/env python3
import imaplib, email, os, json, requests
from email.header import decode_header
from datetime import datetime, timedelta
import pytz

KST = pytz.timezone('Asia/Seoul')

def log(msg):
    print(msg, flush=True)

def check_gmail_for_github_failures():
    """Gmail IMAP으로 GitHub Actions 실패 이메일 체크 (읽지 않은 것만)"""
    mail = imaplib.IMAP4_SSL('imap.gmail.com')
    mail.login(os.environ['GMAIL_ADDRESS'], os.environ['GMAIL_APP_PASSWORD'])
    mail.select('inbox')

    # 최근 3일 이내 + 읽지 않은 + GitHub 발신 + failed 제목
    since_date = (datetime.now() - timedelta(days=3)).strftime('%d-%b-%Y')
    status, messages = mail.search(
        None,
        f'(FROM "noreply@github.com" SINCE {since_date} UNSEEN SUBJECT "failed")'
    )

    failures = []
    if status == 'OK' and messages[0]:
        for eid in messages[0].split():
            s, data = mail.fetch(eid, '(RFC822)')
            if s != 'OK':
                continue
            msg = email.message_from_bytes(data[0][1])
            raw_subject = decode_header(msg['Subject'])[0][0]
            subject = raw_subject.decode() if isinstance(raw_subject, bytes) else raw_subject
            failures.append(subject)
            # 읽음 처리 (중복 알림 방지)
            mail.store(eid, '+FLAGS', '\\Seen')

    mail.logout()
    return failures

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
        "link": {
            "web_url": "https://github.com/KIMMINGYU99/sunday-maple-alert/actions",
            "mobile_web_url": "https://github.com/KIMMINGYU99/sunday-maple-alert/actions"
        }
    }
    resp = requests.post(
        'https://kapi.kakao.com/v2/api/talk/memo/default/send',
        headers={
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/x-www-form-urlencoded'
        },
        data={'template_object': json.dumps(template, ensure_ascii=False)},
        timeout=10
    )
    result = resp.json()
    if result.get('result_code') != 0:
        raise RuntimeError(f"카카오톡 전송 실패: {result}")
    log("카카오톡 전송 완료!")

def main():
    log(f"알림이 실행 - {datetime.now(KST).strftime('%Y-%m-%d %H:%M KST')}")
    log("Gmail 체크 중...")

    failures = check_gmail_for_github_failures()

    if not failures:
        log("새로운 GitHub Actions 실패 없음. 정상!")
        return

    log(f"실패 {len(failures)}건 발견 → 카카오 전송")

    now_str = datetime.now(KST).strftime('%m/%d %H:%M')
    lines = [f"[알림이] GitHub Actions 실패 ({now_str})"]
    for f in failures[:5]:
        lines.append(f"• {f}")
    if len(failures) > 5:
        lines.append(f"... 외 {len(failures)-5}건")
    lines.append("")
    lines.append("Secrets > KAKAO_REFRESH_TOKEN 갱신 필요할 수 있음")

    message = "\n".join(lines)
    if len(message) > 200:
        message = message[:197] + "..."

    access_token = get_kakao_access_token()
    send_kakao_message(access_token, message)

if __name__ == '__main__':
    main()
