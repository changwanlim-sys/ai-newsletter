import os
import json
# Force redeploy v5
import time
import feedparser
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta, timezone
import google.generativeai as genai
from pathlib import Path
import socket
import concurrent.futures

def get_config_path():
    path = Path(__file__).parent / "config_biz.json"
    if path.exists(): return path
    path = Path(__file__).parent.parent / "config_biz.json"
    if path.exists(): return path
    return Path("config_biz.json")

def get_feeds_path():
    path = Path(__file__).parent / "rss_feeds.json"
    if path.exists(): return path
    path = Path(__file__).parent.parent / "rss_feeds.json"
    if path.exists(): return path
    return Path("rss_feeds.json")

def get_schedule_path():
    path = Path(__file__).parent / "schedule_config.json"
    if path.exists(): return path
    path = Path(__file__).parent.parent / "schedule_config.json"
    if path.exists(): return path
    return Path("schedule_config.json")

CONFIG_PATH = get_config_path()
FEEDS_PATH = get_feeds_path()
SCHEDULE_PATH = get_schedule_path()

def load_config():
    config = {}
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            config = json.load(f)
    
    # rss_feeds.json 보충 (GitHub 연동용)
    if FEEDS_PATH.exists():
        try:
            with open(FEEDS_PATH, "r", encoding="utf-8") as f:
                feeds = json.load(f)
                if feeds: config["rss_feeds"] = feeds
        except: pass
    
    # schedule_config.json 보충 (GitHub 연동용)
    if SCHEDULE_PATH.exists():
        try:
            with open(SCHEDULE_PATH, "r", encoding="utf-8") as f:
                schedule = json.load(f)
                if schedule: config["schedule_settings"] = schedule
        except: pass
    
    # Vercel 환경 변수 우선순위 (보안상 권장)
    env_mapping = {
        "GEMINI_API_KEY": "gemini_api_key",
        "EMAIL_SENDER": "email_sender",
        "EMAIL_PASSWORD": "email_password",
        "EMAIL_RECEIVER": "email_receiver"
    }
    for env_key, config_key in env_mapping.items():
        val = os.getenv(env_key)
        if val: config[config_key] = val
        
    if not config:
        print(f"Warning: Configuration not found.")
    return config

def save_config(config):
    try:
        # 민감 정보 제외하고 rss_feeds.json 업데이트
        if "rss_feeds" in config:
            try:
                with open(FEEDS_PATH, "w", encoding="utf-8") as f:
                    json.dump(config["rss_feeds"], f, indent=2, ensure_ascii=False)
            except: pass
            
        # schedule_config.json 업데이트
        if "schedule_settings" in config:
            try:
                with open(SCHEDULE_PATH, "w", encoding="utf-8") as f:
                    json.dump(config["schedule_settings"], f, indent=2, ensure_ascii=False)
            except: pass
        
        # 전체 설정은 로컬에만 저장
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving config: {e}")

def fetch_single_feed(url, days=1):
    # 각 피드별 타임아웃 설정 (10초)
    socket.setdefaulttimeout(10)
    try:
        feed = feedparser.parse(url)
        if feed.bozo: # 파싱 에러 발생 시
            return []
            
        entries = []
        # Use UTC for consistency, similar to the original fetch_news logic
        now_utc = datetime.now(timezone.utc)
        time_limit = now_utc - timedelta(days=days)

        for entry in feed.entries:
            published_struct = entry.get("published_parsed") or entry.get("updated_parsed")
            if published_struct:
                # Convert to UTC datetime object
                published_dt = datetime.fromtimestamp(time.mktime(published_struct), tz=timezone.utc)
            
                if published_dt > time_limit:
                    entries.append({
                        "title": entry.title,
                        "link": entry.link,
                        "summary": entry.get('summary', ''),
                        "source": feed.feed.get('title', url),
                        "published": published_dt.strftime("%Y-%m-%d %H:%M") # Add published time for consistency
                    })
        return entries
    except Exception as e:
        print(f"Error fetching {url}: {e}")
        return []

def fetch_news(rss_urls, days=1):
    all_entries = []
    print(f"Starting parallel fetch for {len(rss_urls)} sources...")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        # 모든 URL에 대해 비동기 작업 등록
        future_to_url = {executor.submit(fetch_single_feed, url, days): url for url in rss_urls}
        
        for future in concurrent.futures.as_completed(future_to_url):
            url = future_to_url[future]
            try:
                data = future.result()
                all_entries.extend(data)
            except Exception as e:
                print(f"Feed {url} generated an exception: {e}")
                
    print(f"Total entries after filtering: {len(all_entries)}")
    return all_entries

def summarize_with_gemini(entries, api_key, custom_prompt, article_count):
    if not entries:
        return "수집된 뉴스가 없습니다."
    
    print(f"Configuring Gemini with API key: {api_key[:10]}...")
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("models/gemini-flash-latest")
    
    # 기사 목록을 텍스트로 변환
    news_text = "\n".join([f"- [{e['source']}] {e['title']}\n  요약: {e['summary'][:200]}...\n  링크: {e['link']}" for e in entries])
    
    print(f"Preparing prompt with {len(entries)} articles ({len(news_text)} chars)...")
    prompt = f"""
당신은 'AI 1인 창업자'를 위한 비즈니스 뉴스레터 편집장입니다. 
아래 수집된 뉴스 목록에서 다음 조건에 부합하는 기사 {article_count}개를 엄선하여 요약해 주세요.

[요약 조건]
{custom_prompt}

[형식 요구 사항]
1. 언어: 한국어.
2. 형식:
   - 💰 오늘의 주요 비즈니스 뉴스 (Top Stories)
   - 🛠 신규 AI 도구 및 기술 동향
   - 🚀 1인 창업자를 위한 인사이트 및 기회

각 기사별로 [제목], [내용 요약], [창업자 관점 인사이트]를 포함해 주세요.

[뉴스 목록]
{news_text}
"""
    
    print("Calling Gemini API (generate_content)...")
    try:
        response = model.generate_content(prompt)
        print("Gemini response received.")
        return response.text
    except Exception as e:
        print(f"Gemini API Error: {str(e)}")
        return f"Gemini 요약 오류: {str(e)}"

def create_email_content(summary_text):
    # 프리미엄한 HTML 템플릿
    html = f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: 'Pretendard', sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px; background-color: #f9f9f9; }}
        .header {{ background: linear-gradient(135deg, #1a1d27, #4f8ef7); color: white; padding: 30px; border-radius: 12px 12px 0 0; text-align: center; }}
        .header h1 {{ margin: 0; font-size: 24px; }}
        .content {{ background: white; padding: 30px; border-radius: 0 0 12px 12px; border: 1px solid #eee; border-top: none; white-space: pre-line; }}
        .footer {{ text-align: center; margin-top: 20px; font-size: 12px; color: #999; }}
        .tag {{ display: inline-block; background: #eef4ff; color: #4f8ef7; padding: 4px 10px; border-radius: 20px; font-size: 12px; font-weight: bold; margin-bottom: 15px; }}
    </style>
</head>
<body>
    <div class="header">
        <div class="tag">AI Solo Entrepreneur</div>
        <h1>AI 비즈니스 뉴스레터</h1>
        <p>{datetime.now().strftime('%Y년 %m월 %d일 %p %I시 발송')}</p>
    </div>
    <div class="content">
{summary_text}
    </div>
    <div class="footer">
        보낸이: Antigravity AI Newsletter Bot<br>
        본 메일은 설정된 스케줄에 따라 자동으로 생성되었습니다.
    </div>
</body>
</html>
"""
    return html

def send_email(config, html_content):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"🚀 [AI 비즈니스 뉴스레터] {datetime.now().strftime('%m/%d')} 주요 소식"
    msg["From"] = config["email_sender"]
    msg["To"] = config["email_receiver"]
    
    msg.attach(MIMEText(html_content, "html"))
    
def send_email(config, html_content):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"🚀 [AI 비즈니스 뉴스레터] {datetime.now().strftime('%m/%d')} 주요 소식"
    msg["From"] = config["email_sender"]
    msg["To"] = config["email_receiver"]
    
    msg.attach(MIMEText(html_content, "html"))
    
    try:
        with smtplib.SMTP(config["smtp_server"], config["smtp_port"], timeout=15) as server:
            server.starttls()
            server.login(config["email_sender"], config["email_password"])
            server.send_message(msg)
        print("Email sent successfully!")
        return True, "Success"
    except Exception as e:
        error_msg = str(e)
        print(f"Failed to send email: {error_msg}")
        return False, error_msg

def run_newsletter(dry_run=False, test_email=False):
    """generator가 아닌 일반 함수 버전을 제공하여 기존 코드 호환성 유지"""
    last_msg = ""
    for msg in run_newsletter_generator(dry_run, test_email):
        if msg != "[DONE]":
            last_msg = msg
    return last_msg

def run_newsletter_generator(dry_run=False, test_email=False):
    yield "--- 1. 설정 확인 및 뉴스 수집 시작 ---"
    config = load_config()
    if not config: 
        yield "오류: 설정을 불러올 수 없습니다."
        return
    
    if config["gemini_api_key"] == "YOUR_GEMINI_API_KEY":
        yield "오류: Gemini API 키가 설정되지 않았습니다."
        return

    yield f"총 {len(config['rss_feeds'])}개의 소스에서 뉴스 탐색 중..."
    entries = fetch_news(config["rss_feeds"])
    yield f"성공: 최근 24시간 내 {len(entries)}개의 기사를 찾았습니다."
    
    if not entries:
        yield "알림: 새로운 기사가 없어 작업을 중단합니다."
        return

    yield "--- 2. Gemini AI 요약 진행 중 (약 20~40초 소요) ---"
    summary = summarize_with_gemini(
        entries, 
        config["gemini_api_key"], 
        config.get("custom_prompt", ""), 
        config.get("article_count", 5)
    )
    
    if dry_run:
        yield "--- 드라이 런 완료: 아래는 요약된 미리보기입니다 ---"
        # 요약 내용에 뉴라인이 많으므로 줄바꿈 단위로 쪼개서 보냅니다
        for line in summary.split('\n'):
            if line.strip():
                yield line
        yield "[DONE]"
        return

    yield "--- 3. 뉴스레터 이메일 본문 생성 중 ---"
    html_content = create_email_content(summary)
    
    if test_email:
        yield "--- 테스트 이메일 발송 중 ---"
    else:
        yield f"--- 4. 뉴스레터 발송 중 ({config['email_receiver']}) ---"
    
    success, error_msg = send_email(config, html_content)
    if success:
        if not test_email:
            config["last_run"] = datetime.now().isoformat()
            save_config(config)
        yield "✅ 뉴스레터 발송이 성공적으로 완료되었습니다!"
    else:
        yield f"❌ 이메일 발송 실패: {error_msg}"
    
    yield "[DONE]"

# End of ai_biz_newsletter.py

if __name__ == "__main__":
    import sys
    dry_run = "--dry-run" in sys.argv
    test_email = "--test-email" in sys.argv
    run_newsletter(dry_run, test_email)
