# Force redeploy v8 (Final Sync)
import os
import sys

# 디버깅 로그 (Vercel 로그에서 확인 가능)
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.abspath(os.path.join(current_dir, '..'))

print(f"--- Vercel Debug Info ---")
print(f"Current Dir: {current_dir}")
print(f"Parent Dir: {parent_dir}")
try:
    print(f"Files in root: {os.listdir(parent_dir)}")
except:
    print("Could not list parent dir")

# 프로젝트 루트를 경로 맨 앞에 추가
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# 이제 루트에 있는 admin_server를 불러올 수 있습니다
try:
    from admin_server import app
    print("SUCCESS: Imported app from admin_server")
except Exception as e:
    print(f"ERROR: Failed to import admin_server: {e}")
    # 다시 시도 (가끔 늦게 로드되기도 함)
    sys.path.append(parent_dir)
    from admin_server import app

# Vercel용 핸들러
app = app

@app.route('/debug-v7')
def debug_version():
    return "DEPLOYMENT_V7_SUCCESS (Code is latest!)"
