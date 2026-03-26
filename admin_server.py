import os
import json
# Force redeploy v6 (Detail Error Log Active)
import subprocess
import time
import threading
from flask import Flask, render_template, request, jsonify, Response
from pathlib import Path
from ai_biz_newsletter import load_config, save_config, run_newsletter, run_newsletter_generator, CONFIG_PATH

app = Flask(__name__, 
            template_folder=os.path.abspath(os.path.join(os.path.dirname(__file__), 'templates')),
            static_folder=os.path.abspath(os.path.join(os.path.dirname(__file__), 'static')))

# Vercel 환경 체크
IS_VERCEL = "VERCEL" in os.environ

@app.route('/')
def index():
    config = load_config()
    return render_template('index.html', config=config)

@app.route('/api/config', methods=['GET', 'POST'])
def handle_config():
    if request.method == 'POST':
        new_config = request.json
        save_config(new_config)
        return jsonify({"status": "success"})
    return jsonify(load_config())

@app.route('/api/run-test', methods=['POST'])
def run_test():
    try:
        # Dry run results
        summary = run_newsletter(dry_run=True)
        return jsonify({"status": "success", "summary": summary})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/send-now', methods=['POST'])
def send_now():
    try:
        # run_newsletter는 이제 generator의 마지막 메시지(성공/실패 문자열)를 반환합니다.
        result_msg = run_newsletter(dry_run=False)
        if "성공" in result_msg:
            return jsonify({"status": "success"})
        else:
            return jsonify({"status": "error", "message": result_msg})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/stream-run', methods=['GET'])
def stream_run():
    dry_run = request.args.get('dry_run', 'false').lower() == 'true'
    
    def generate():
        for step in run_newsletter_generator(dry_run=dry_run):
            # SSE 형식으로 데이터 전송
            yield f"data: {step}\n\n"
    
    return Response(generate(), mimetype='text/event-stream')

@app.route('/api/send-content', methods=['POST'])
def send_content():
    try:
        content = request.json.get('content')
        if not content:
            return jsonify({"status": "error", "message": "발송할 내용이 없습니다."})
        
        from ai_biz_newsletter import create_email_content, send_email
        config = load_config()
        html_content = create_email_content(content)
        
        success, error_msg = send_email(config, html_content)
        if success:
            return jsonify({"status": "success"})
        else:
            return jsonify({"status": "error", "message": error_msg})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/update-schedule', methods=['POST'])
def update_schedule():
    if IS_VERCEL:
        return jsonify({"status": "error", "message": "Vercel(클라우드) 환경에서는 윈도우 스케줄러를 직접 수정할 수 없습니다. 대신 Vercel Cron을 사용해 주세요."})
    
    # schedule_newsletter.ps1을 실행하여 윈도우 스케줄러 업데이트
    try:
        cmd = ["powershell.exe", "-ExecutionPolicy", "Bypass", "-File", "./schedule_newsletter.ps1"]
        subprocess.run(cmd, check=True, capture_output=True)
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

import time
import threading

# 마지막 하트비트 시간 기록
last_heartbeat = time.time()

def shutdown_monitor():
    global last_heartbeat
    while True:
        time.sleep(5)
        # 10초 이상 하트비트가 없으면 종료
        if time.time() - last_heartbeat > 10:
            print("No heartbeat detected. Shutting down admin server...")
            os._exit(0)

@app.route('/api/heartbeat', methods=['POST'])
def heartbeat():
    global last_heartbeat
    last_heartbeat = time.time()
    return jsonify({"status": "ok"})

@app.route('/api/shutdown', methods=['POST'])
def shutdown():
    print("Manual shutdown requested. Shutting down...")
    os._exit(0)
    return jsonify({"status": "shutdown"})

if __name__ == '__main__':
    # 하트비트 모니터링 스레드 시작
    threading.Thread(target=shutdown_monitor, daemon=True).start()
    
    # 템플릿 폴더가 없으면 생성
    os.makedirs('templates', exist_ok=True)
    os.makedirs('static', exist_ok=True)
    app.run(debug=True, port=5000, use_reloader=False) # use_reloader=False로 스레드 중복 방지
