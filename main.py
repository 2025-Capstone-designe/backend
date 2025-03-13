from fastapi import *
from fastapi.responses import StreamingResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import mysql.connector
from math import sqrt
from datetime import datetime
import os
import cv2
import numpy as np
import threading
from dotenv import load_dotenv
import time
from datetime import datetime, timezone
import pytz

# 대한민국 표준시 구하기
def convert_utc_to_kst():
    # UTC 시간 구하기
    utc_time = datetime.now(pytz.utc)
    
    # 대한민국 표준시로 변환
    kst_timezone = pytz.timezone('Asia/Seoul')
    kst_time = utc_time.astimezone(kst_timezone)
    
    # 문자열로 포맷팅하여 반환
    return kst_time.strftime("%Y-%m-%d %H:%M:%S")

# 함수 호출 예시
time = convert_utc_to_kst()
#uvicorn main:app --reload

app = FastAPI()
load_dotenv()

origins = [
	"*"
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", response_class=HTMLResponse)
def read_root():
    html_content = '''<!DOCTYPE html>
        <html lang="ko">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>카메라 미리보기</title>
            <style>
                body {
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    height: 100vh;
                    background-color: #f4f4f4;
                }
                video {
                    border: 2px solid black;
                    border-radius: 10px;
                }
            </style>
        </head>
        <body>
            <video id="camera" autoplay playsinline></video>
            <script>
                async function startCamera() {
                    try {
                        const stream = await navigator.mediaDevices.getUserMedia({ video: true });

                        // 스트림을 복제하여 사용
                        const clonedStream = stream.clone();
            
                        document.getElementById('camera').srcObject = clonedStream;
                    } catch (error) {
                        console.error("카메라 접근 실패:", error);
                    }
                }
                startCamera();
            </script>
        </body>
        </html>
        '''
    return HTMLResponse(content=html_content, status_code=200)
    # return {"Service Availalble!"}

# 데이터베이스 연결
# database 정보
db_config = {
    "host": os.getenv("DB_HOST", "34.64.109.121"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "database": os.getenv("DB_NAME"),
    "port": int(os.getenv("DB_PORT", 3306)),
}

# 데이터베이스에 query문 보내는 알고리즘
def fetch_data(query, params=None):
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        cursor.execute(query, params or ())
        result = cursor.fetchall()
        cursor.close()
        conn.close()
        return result
    except mysql.connector.Error as err:
        raise HTTPException(status_code=500, detail=f"Database error: {err}")
    # finally:
        # cursor.close()
        # conn.close()

class TrackingData(BaseModel):
    x: float
    y: float

# 거리 계산 알고리즘
def calculate_distance(x1, y1, x2, y2):
    if x1 is None or y1 is None:
        return 0  # 첫 번째 데이터는 이동 거리 없음
    return ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5

def get_previous_coordinates(tracking_date):
    query = """
        SELECT x, y FROM tracking_data 
        WHERE DATE(time) = %s 
        ORDER BY time DESC 
        LIMIT 1
    """
    result = fetch_data(query, (tracking_date,))
    return result[0] if result else (None, None)

# 위치, 거리, 시간 데이터베이스에 저장 알고리즘
@app.post("/tracking_data")
def save_tracking_data(tracking: TrackingData):
    try:
        # 시간 구하기
        time = convert_utc_to_kst()

        # 이전 좌표 가져오기
        today_date = time.split(" ")[0]
        previous_x, previous_y = get_previous_coordinates(today_date)

        # 거리 계산
        distance = calculate_distance(previous_x, previous_y, tracking.x, tracking.y)
        
        # MySQL에 데이터 저장
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        query = "INSERT INTO tracking_data (x, y, time, distance) VALUES (%s, %s, %s, %s)"
        cursor.execute(query, (tracking.x, tracking.y, time, distance))
        conn.commit()
        cursor.close()
        conn.close()

        return {
            "message": "Tracking data saved",
            "x": tracking.x,
            "y": tracking.y,
            "time": time,
            "calculated_distance": distance,
        }
    except Exception as e:
        return {"error": str(e)}

# 총 이동 거리 반환 알고리즘    
@app.get("/daily_movement")
def get_total_movement():
    today_date = datetime.now().strftime('%Y-%m-%d')
    query = """
        SELECT COALESCE(SUM(distance), 0) FROM tracking_data 
            WHERE DATE(time) = %s
    """
    result = fetch_data(query, (today_date,))
    total_distance = result[0][0] if result and result[0][0] else 0  # None 방지
    
    return {"date": today_date, "total_movement": total_distance}

# 최근 10개 데이터 반환 알고리즘
@app.get("/recent_movements")
def get_recent_movements():
    query = """
        SELECT time, x, y 
        FROM tracking_data 
        ORDER BY time DESC 
        LIMIT 10
    """
    recent_movements = fetch_data(query)
    result = [{"time": row[0], "x": row[1], "y": row[2]} for row in recent_movements]
    
    return {"recent_movements": result}

print("hell0")