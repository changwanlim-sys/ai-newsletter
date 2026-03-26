import os
import sys
from datetime import datetime
import pytz # timezone 처리를 위해 필요

# 프로젝트 루트(상위 디렉토리)를 Python 경로 맨 앞에 추가
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.abspath(os.path.join(current_dir, '..'))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from ai_biz_newsletter import load_config, run_newsletter

def handler(request):
    """Vercel Cron Job용 핸들러 (매 시간 실행 설정 권장)"""
    config = load_config()
    schedule = config.get("schedule_settings", {})
    
    if not schedule or schedule.get("type") != "daily":
        return "No daily schedule configured"

    # 한국 시간(KST) 기준으로 현재 시간 확인
    tz_kst = pytz.timezone('Asia/Seoul')
    now = datetime.now(tz_kst)
    current_hour = now.hour
    current_minute = now.minute

    print(f"Cron check at {now.strftime('%Y-%m-%d %H:%M:%S')} KST")

    # 스케줄에 등록된 시간들과 비교 (오차 범위 30분 내외면 실행)
    should_run = False
    for t in schedule.get("times", []):
        sched_hour = t["hour"]
        if t["period"] == "PM" and sched_hour < 12:
            sched_hour += 12
        elif t["period"] == "AM" and sched_hour == 12:
            sched_hour = 0
            
        # 현재 시간이 스케줄 시간과 일치하는지 확인 (매 시간 실행되므로 hour만 체크해도 충분)
        if current_hour == sched_hour:
            should_run = True
            break
            
    if should_run:
        print(f"Schedule matched! Running newsletter...")
        result = run_newsletter(dry_run=False)
        return f"Newsletter sent: {result}"
    
    return "Not the scheduled time yet."

# Vercel Serverless Function으로 동작하기 위한 기본 진입점
if __name__ == "__main__":
    # 로컬 테스트용
    print(handler(None))
