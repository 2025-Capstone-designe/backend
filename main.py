from fastapi import *
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime, date
from datetime import timedelta
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

# ✅ 시간 변환
def convert_utc_to_kst():
    utc_time = datetime.now(pytz.utc)
    kst = pytz.timezone("Asia/Seoul")
    return utc_time.astimezone(kst).strftime("%Y-%m-%d %H:%M:%S")

@app.get("/", response_class=HTMLResponse)
def read_root():
    try:
        conn = mysql.connector.connect(**db_config)
        conn.close()
        status_msg = "✅ 데이터베이스 연결 성공"
    except Exception as e:
        status_msg = f"❌ 데이터베이스 연결 실패: {e}"

    html_content = f"""
    <!DOCTYPE html>
    <html lang="ko">
    <head><meta charset="UTF-8"><title>서버 상태</title></head>
    <body>
        <h1>서버 상태 확인</h1>
        <p>{status_msg}</p>
        <p>서버가 정상적으로 작동 중입니다.</p>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content, status_code=200)

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
    query = "SELECT x, y FROM behavior_log WHERE DATE(timestamp) = %s ORDER BY timestamp DESC LIMIT 1"
    result = fetch_data(query, (tracking_date,))
    return (result[0]['x'], result[0]['y']) if result else (None, None)

# ✅ 데이터 모델
class TrackingData(BaseModel):
    timestamp: datetime
    x: float
    y: float
    home_data: int
    eating_data: int
    drinking_data: int

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
            home_data TINYINT(1),
            eating_data TINYINT(1),
            drinking_data TINYINT(1)
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

# ✅ 최근 좌표 10개 (timestamp, x, y)
@app.get("/recent_movements")
def get_recent_movements():
    result = fetch_data(
        "SELECT timestamp, x, y FROM behavior_log WHERE x IS NOT NULL AND y IS NOT NULL ORDER BY timestamp DESC LIMIT 10"
    )
    return {"recent_movements": result}

from datetime import timedelta

# ✅ 식사 시간 조회 + 전날 평균 (뷰 eating_log 사용)
@app.get("/get_diet_info")
def get_diet_time(query_date: date):
    current = fetch_data("""
        SELECT COUNT(*) AS total 
        FROM eating_log 
        WHERE DATE(timestamp) = %s
    """, (query_date,))

    prev_date = query_date - timedelta(days=1)
    previous = fetch_data("""
        SELECT COUNT(*) AS total 
        FROM eating_log 
        WHERE DATE(timestamp) = %s
    """, (prev_date,))

    return {
        "date": str(query_date),
        "total_diet": int(current[0]['total']),
        "prev_avg_diet": int(previous[0]['total']),
        "prev_date": str(prev_date)
    }

# ✅ 수분 시간 조회 + 전날 평균 (뷰 drinking_log 사용)
@app.get("/get_water_info")
def get_water_time(query_date: date):
    current = fetch_data("""
        SELECT COUNT(*) AS total 
        FROM drinking_log 
        WHERE DATE(timestamp) = %s
    """, (query_date,))

    prev_date = query_date - timedelta(days=1)
    previous = fetch_data("""
        SELECT COUNT(*) AS total 
        FROM drinking_log 
        WHERE DATE(timestamp) = %s
    """, (prev_date,))

    return {
        "date": str(query_date),
        "total_water": int(current[0]['total']),
        "prev_avg_water": int(previous[0]['total']),
        "prev_date": str(prev_date)
    }

# ✅ 휴식 시간 계산 + 전날 평균 (뷰 home_log 사용)
@app.get("/get_sleep_info")
def get_sleep_time(query_date: date):
    result_today = fetch_data("""
        SELECT 
            (SELECT COUNT(*) FROM home_log WHERE DATE(timestamp) = %s) AS total,
            (SELECT COUNT(*) FROM eating_log WHERE DATE(timestamp) = %s) AS eat,
            (SELECT COUNT(*) FROM drinking_log WHERE DATE(timestamp) = %s) AS drink
    """, (query_date, query_date, query_date))

    prev_date = query_date - timedelta(days=1)
    result_prev = fetch_data("""
        SELECT 
            (SELECT COUNT(*) FROM home_log WHERE DATE(timestamp) = %s) AS total,
            (SELECT COUNT(*) FROM eating_log WHERE DATE(timestamp) = %s) AS eat,
            (SELECT COUNT(*) FROM drinking_log WHERE DATE(timestamp) = %s) AS drink
    """, (prev_date, prev_date, prev_date))

    total, eat, drink = result_today[0]['total'], result_today[0]['eat'], result_today[0]['drink']
    prev_total, prev_eat, prev_drink = result_prev[0]['total'], result_prev[0]['eat'], result_prev[0]['drink']

    relaxing = max(86400 - total - eat - drink, 0)
    prev_relaxing = max(86400 - prev_total - prev_eat - prev_drink, 0)

    return {
        "date": str(query_date),
        "total_sleep": float(relaxing),
        "prev_avg_sleep": float(prev_relaxing),
        "prev_date": str(prev_date)
    }
