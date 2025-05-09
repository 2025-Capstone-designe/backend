from fastapi import *
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime, date
import mysql.connector
import os
from dotenv import load_dotenv
import pytz
import logging
from math import sqrt

# 🔼 .env 파일 불러오기
load_dotenv()

# ✅ 로그 설정
logging.basicConfig(level=logging.INFO)

# ✅ 시간 변환
def convert_utc_to_kst():
    utc_time = datetime.now(pytz.utc)
    kst = pytz.timezone("Asia/Seoul")
    return utc_time.astimezone(kst).strftime("%Y-%m-%d %H:%M:%S")

# ✅ FastAPI 및 환경변수 로드
app = FastAPI()
load_dotenv()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/", response_class=HTMLResponse)
def read_root():
    return HTMLResponse(content="""
        <!DOCTYPE html>
        <html lang="ko">
        <head><meta charset="UTF-8"><title>카메라 미리보기</title></head>
        <body><video id="camera" autoplay playsinline></video>
        <script>
            navigator.mediaDevices.getUserMedia({ video: true })
                .then(stream => document.getElementById('camera').srcObject = stream)
                .catch(error => console.error("카메라 접근 실패:", error));
        </script></body></html>
    """, status_code=200)

# ✅ DB 연결 설정
db_config = {
    "host": os.getenv("DB_HOST"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "database": os.getenv("DB_NAME"),
    "port": int(os.getenv("DB_PORT", 3306)),
}

# ✅ 거리 계산 함수
def calculate_distance(x1, y1, x2, y2):
    if None in (x1, y1, x2, y2):
        return 0.0
    return round(sqrt((x2 - x1)**2 + (y2 - y1)**2), 4)

# ✅ SELECT 전용 유틸
def fetch_data(query, params=None):
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)
        cursor.execute(query, params or ())
        result = cursor.fetchall()
        cursor.close()
        conn.close()
        return result
    except mysql.connector.Error as err:
        raise HTTPException(status_code=500, detail=f"DB 오류: {err}")

# ✅ 마지막 좌표 조회
def get_previous_coordinates(tracking_date):
    query = "SELECT x, y FROM behavior_log WHERE detected = 1 AND DATE(timestamp) = %s ORDER BY timestamp DESC LIMIT 1"
    result = fetch_data(query, (tracking_date,))
    return (result[0]['x'], result[0]['y']) if result else (None, None)

# ✅ 데이터 모델
class TrackingData(BaseModel):
    timestamp: datetime
    x: float
    y: float
    detected: int
    prox: int
    prox_type: str

# ✅ 테이블 생성
@app.on_event("startup")
def create_behavior_log_table():
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS behavior_log (
            id INT AUTO_INCREMENT PRIMARY KEY,
            timestamp DATETIME NOT NULL,
            x FLOAT,
            y FLOAT,
            distance FLOAT,
            detected TINYINT(1),
            prox TINYINT(1),
            prox_type VARCHAR(20)
        )
        """)
        conn.commit()
        logging.info("✅ behavior_log 테이블 생성 완료")
    except Exception as e:
        logging.error(f"❌ 테이블 생성 실패: {e}")
    finally:
        cursor.close()
        conn.close()

# ✅ 데이터 저장 API
@app.post("/tracking_data")
def save_tracking_data(data: TrackingData):
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()

        # 이전 좌표로부터 거리 계산
        x1, y1 = get_previous_coordinates(data.timestamp.date())
        dist = calculate_distance(x1, y1, data.x, data.y)

        # 저장
        cursor.execute("""
            INSERT INTO behavior_log (timestamp, x, y, distance, detected, prox, prox_type)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (data.timestamp, data.x, data.y, dist, data.detected, data.prox, data.prox_type))
        conn.commit()
        return {
            "message": "Tracking data saved",
            "x": data.x,
            "y": data.y,
            "time": data.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "calculated_distance": dist,
            "detected": data.detected
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB 저장 오류: {e}")
    finally:
        cursor.close()
        conn.close()

# ✅ 하루 총 이동 거리
@app.get("/daily_movement")
def get_daily_movement(query_date: date):
    result = fetch_data(
        "SELECT SUM(distance) AS total FROM behavior_log WHERE DATE(timestamp) = %s AND detected = 1",
        (query_date,)
    )
    return {
        "date": str(query_date),
        "total_movement": round(result[0]['total'] or 0.0, 4)
    }

# ✅ 최근 좌표 10개
@app.get("/recent_movements")
def get_recent_movements():
    result = fetch_data(
        "SELECT timestamp AS time, x, y FROM behavior_log WHERE detected = 1 ORDER BY timestamp DESC LIMIT 10"
    )
    return {"recent_movements": result}

# ✅ 식사 시간 조회
@app.get("/get_diet_info")
def get_diet_time(query_date: date):
    result = fetch_data(
        "SELECT COUNT(*) AS total FROM behavior_log WHERE prox = 1 AND prox_type = 'eating' AND DATE(timestamp) = %s",
        (query_date,)
    )
    return {"date": str(query_date), "total_diet": float(result[0]['total'])}

# ✅ 수분 시간 조회
@app.get("/get_water_info")
def get_water_time(query_date: date):
    result = fetch_data(
        "SELECT COUNT(*) AS total FROM behavior_log WHERE prox = 1 AND prox_type = 'drinking' AND DATE(timestamp) = %s",
        (query_date,)
    )
    return {"date": str(query_date), "total_water": float(result[0]['total'])}

# ✅ 휴식 시간 계산
@app.get("/get_sleep_info")
def get_sleep_time(query_date: date):
    result = fetch_data(
        "SELECT " +
        "(SELECT COUNT(*) FROM behavior_log WHERE detected = 1 AND DATE(timestamp) = %s) AS move, " +
        "(SELECT COUNT(*) FROM behavior_log WHERE prox = 1 AND prox_type = 'eating' AND DATE(timestamp) = %s) AS eat, " +
        "(SELECT COUNT(*) FROM behavior_log WHERE prox = 1 AND prox_type = 'drinking' AND DATE(timestamp) = %s) AS drink",
        (query_date, query_date, query_date)
    )
    move, eat, drink = result[0]['move'], result[0]['eat'], result[0]['drink']
    relaxing = max(86400 - move - eat - drink, 0)
    return {"date": str(query_date), "total_sleep": float(relaxing)}