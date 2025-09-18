import os
from fastapi.encoders import jsonable_encoder
import pytz
from openai import OpenAI
import logging
from fastapi import *
import mysql.connector
from dotenv import load_dotenv
from pydantic import BaseModel
from fastapi.responses import HTMLResponse
from datetime import datetime, date, timedelta
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# 로그 설정
logging.basicConfig(level=logging.INFO)

# FastAPI 및 환경변수 로드
app = FastAPI()
load_dotenv()

# DB 연결 설정
db_config = {
    "host": os.getenv("DB_HOST"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "database": os.getenv("DB_NAME"),
    "port": int(os.getenv("DB_PORT", 3306)),
}

# openai API 키
openai_key = os.getenv("OPENAI_KEY")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 시간 변환
def convert_utc_to_kst():
    utc_time = datetime.now(pytz.utc)
    # print(f"UTC Time: {utc_time}")
    kst = pytz.timezone("Asia/Seoul")
    # print(f"KST Timezone: {kst}")
    # print(utc_time.astimezone(kst).strftime("%Y-%m-%d %H:%M:%S"))
    return utc_time.astimezone(kst).strftime("%Y-%m-%d %H:%M:%S")


def get_review(
    api_key: str,
    avg_meal: float, avg_water: float, avg_rest: float,
    cur_meal: float, cur_water: float, cur_rest: float,
    time: str
) -> str:
    client = OpenAI(api_key=api_key)

    prompt = f"""
    다음은 어떤 개체의 활동 평균과 현재 상태 데이터입니다.

    측정 시간: {time}

    평균 활동량:
    - 식사량: {avg_meal:.1f}g
    - 물 섭취량: {avg_water:.1f}ml
    - 휴식 시간: {avg_rest:.1f}시간

    현재 활동량:
    - 식사량: {cur_meal:.1f}g
    - 물 섭취량: {cur_water:.1f}ml
    - 휴식 시간: {cur_rest:.1f}시간

    이 데이터를 바탕으로 현재 상태에 대한 간단한 요약과 추천 활동(예: 더 쉬어야 함, 수분 섭취 필요 등)을 한국어로 작성해 주세요. 
    문장은 간결하고 직관적으로 만들어 주세요. 두 문단 이내로 작성해 주세요.
    """

    try:
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "당신은 건강 모니터링 데이터를 분석하여 간단한 조언을 해주는 헬스케어 전문가입니다."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=300,
        )

        return response.choices[0].message.content.strip()

    except Exception as e:
        return f"에러 발생: {str(e)}"


@app.get("/", response_class=HTMLResponse)
def read_root():
    try:
        conn = mysql.connector.connect(**db_config)
        conn.close()
        status_msg = "데이터베이스 연결 성공"
    except Exception as e:
        status_msg = f"데이터베이스 연결 실패: {e}"

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

# SELECT 전용 유틸
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

# 데이터 모델
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
            home_data FLOAT,
            eating_data FLOAT,
            drinking_data FLOAT
        )
        """)
        conn.commit()
        logging.info("behavior_log 테이블 생성 완료")
    except Exception as e:
        logging.error(f"테이블 생성 실패: {e}")
    finally:
        cursor.close()
        conn.close()

# gpt조언 받아오기
@app.get("/get_gpt_advice")
def get_gpt_advice():
    try:
        # 평균 식사량 (최근 7일간 하루 평균)
        avg_eat = fetch_data("""
            SELECT AVG(daily_total) as avg_meal FROM (
                SELECT SUM(eating_data) as daily_total
                FROM behavior_log
                WHERE timestamp >= CURDATE() - INTERVAL 7 DAY
                AND eating_data IS NOT NULL AND eating_data > 0
                GROUP BY DATE(timestamp)
            ) AS daily_totals
        """)[0]['avg_meal'] or 0

        # 평균 수분 섭취량 (ml로 변환)
        avg_water = fetch_data("""
            SELECT AVG(daily_total * 3.6) as avg_water FROM (
                SELECT SUM(drinking_data) as daily_total
                FROM behavior_log
                WHERE timestamp >= CURDATE() - INTERVAL 7 DAY
                AND drinking_data IS NOT NULL AND drinking_data > 0
                GROUP BY DATE(timestamp)
            ) AS daily_totals
        """)[0]['avg_water'] or 0

        # 평균 휴식시간 (시간으로 변환)
        avg_rest = fetch_data("""
            SELECT AVG(daily_total / 3600) as avg_rest FROM (
                SELECT SUM(home_data) as daily_total
                FROM behavior_log
                WHERE timestamp >= CURDATE() - INTERVAL 7 DAY
                AND home_data IS NOT NULL AND home_data > 0
                GROUP BY DATE(timestamp)
            ) AS daily_totals
        """)[0]['avg_rest'] or 0

        # 오늘 식사량
        cur_eat = fetch_data("""
            SELECT COALESCE(SUM(eating_data), 0) AS total 
            FROM behavior_log 
            WHERE DATE(timestamp) = CURDATE() AND eating_data IS NOT NULL
        """)[0]['total'] or 0

        # 오늘 수분 섭취량 (ml로 변환)
        cur_water_percent = fetch_data("""
            SELECT COALESCE(SUM(drinking_data), 0) AS total 
            FROM behavior_log 
            WHERE DATE(timestamp) = CURDATE() AND drinking_data IS NOT NULL
        """)[0]['total'] or 0
        cur_water = cur_water_percent * 3.6  # ml로 변환

        # 오늘 휴식시간 (시간으로 변환)
        cur_rest_seconds = fetch_data("""
            SELECT COALESCE(SUM(home_data), 0) AS total 
            FROM behavior_log 
            WHERE DATE(timestamp) = CURDATE() AND home_data IS NOT NULL
        """)[0]['total'] or 0
        cur_rest = cur_rest_seconds / 3600  # 시간으로 변환

        # 현재 시각 (KST)
        now_kst = convert_utc_to_kst()

        # GPT 리뷰 생성
        advice = get_review(
            api_key=openai_key,
            avg_meal=avg_eat,
            avg_water=avg_water,
            avg_rest=avg_rest,
            cur_meal=cur_eat,
            cur_water=cur_water,
            cur_rest=cur_rest,
            time=now_kst
        )

        return {
            "advice": advice
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"GPT 조언 생성 오류: {e}")

# 하루 총 이동 거리 (KST 기준 오늘 날짜 사용)
@app.get("/daily_movement")
def get_daily_movement():
    kst_now = convert_utc_to_kst()
    query_date = kst_now.split(" ")[0]  # YYYY-MM-DD 형태 추출

    result = fetch_data(
        "SELECT SUM(distance) AS total FROM behavior_log WHERE DATE(timestamp) = %s",
        (query_date,)
    )
    return {
        "date": str(query_date),
        "total_movement": round(result[0]['total'] or 0.0, 4)
    }

# 최근 좌표 10개 (timestamp, x, y) - 최신 10개를 제외한 그 다음 10개
@app.get("/recent_movements")
def get_recent_movements(isfirst: int = 0):
    if isfirst == 1:
        result = fetch_data(
            "SELECT x, y FROM behavior_log WHERE x IS NOT NULL AND y IS NOT NULL ORDER BY timestamp DESC LIMIT 10 OFFSET 1"
        )
    else:
        result = fetch_data(
            "SELECT x, y FROM behavior_log WHERE x IS NOT NULL AND y IS NOT NULL ORDER BY timestamp DESC LIMIT 1 OFFSET 1"
        )
    return {"recent_movements": result}

# 최근 7일간의 평균 이동 거리
@app.get("/get_tracking_info")
def get_tracking_info():
    query_datetime = convert_utc_to_kst()
    query_date = datetime.strptime(query_datetime, "%Y-%m-%d %H:%M:%S").date()

    # 오늘 날짜의 총 이동 거리
    today_total = fetch_data("""
        SELECT ROUND(SUM(distance), 2) AS total
        FROM behavior_log
        WHERE DATE(timestamp) = %s
    """, (query_date,))[0]['total'] or 0.0

    # 지난 7일간의 하루 평균 이동 거리
    start_date = query_date - timedelta(days=7)
    end_date = query_date - timedelta(days=1)
    past_avg = fetch_data("""
        SELECT ROUND(AVG(daily_total), 2) AS avg_total FROM (
            SELECT DATE(timestamp) AS dt, SUM(distance) AS daily_total
            FROM behavior_log
            WHERE DATE(timestamp) BETWEEN %s AND %s
            GROUP BY DATE(timestamp)
        ) AS daily_distances
    """, (start_date, end_date))[0]['avg_total'] or 0.0

    return {
        "total_movement_today": str(today_total) + "m",
        "avg_movement_past_7days": str(past_avg) + "m"
    }

# 식사량 조회 + 전날 평균
@app.get("/get_diet_info")
def get_diet_time():
    query_datetime = convert_utc_to_kst()
    query_date = datetime.strptime(query_datetime, "%Y-%m-%d %H:%M:%S").date()

    # 오늘 총 식사량
    current = fetch_data("""
        SELECT COALESCE(SUM(eating_data), 0) AS total 
        FROM behavior_log 
        WHERE DATE(timestamp) = %s AND eating_data IS NOT NULL
    """, (query_date,))

    # 지난 7일간 하루 평균 식사량
    start_date = query_date - timedelta(days=7)
    end_date = query_date - timedelta(days=1)
    previous_avg = fetch_data("""
        SELECT ROUND(AVG(daily_total), 0) AS avg_total FROM (
            SELECT SUM(eating_data) AS daily_total
            FROM behavior_log
            WHERE DATE(timestamp) BETWEEN %s AND %s
            AND eating_data IS NOT NULL AND eating_data > 0
            GROUP BY DATE(timestamp)
        ) AS daily_totals
    """, (start_date, end_date))

    return {
        "total_diet": int(current[0]['total']),
        "prev_avg_diet": int(previous_avg[0]['avg_total'] or 0)
    }

# 음수량 조회 + 전날 평균 (ml로 변환)
@app.get("/get_water_info")
def get_water_time():
    query_datetime = convert_utc_to_kst()
    query_date = datetime.strptime(query_datetime, "%Y-%m-%d %H:%M:%S").date()

    # 오늘 총 음수량 (퍼센트를 ml로 변환)
    current = fetch_data("""
        SELECT COALESCE(SUM(drinking_data), 0) * 3.6 AS total 
        FROM behavior_log 
        WHERE DATE(timestamp) = %s AND drinking_data IS NOT NULL
    """, (query_date,))

    # 지난 7일간 하루 평균 음수량 (ml로 변환)
    start_date = query_date - timedelta(days=7)
    end_date = query_date - timedelta(days=1)
    previous_avg = fetch_data("""
        SELECT ROUND(AVG(daily_total * 3.6), 0) AS avg_total FROM (
            SELECT SUM(drinking_data) AS daily_total
            FROM behavior_log
            WHERE DATE(timestamp) BETWEEN %s AND %s
            AND drinking_data IS NOT NULL AND drinking_data > 0
            GROUP BY DATE(timestamp)
        ) AS daily_totals
    """, (start_date, end_date))

    return {
        "total_water": int(current[0]['total']),
        "prev_avg_water": int(previous_avg[0]['avg_total'] or 0)
    }

# 휴식 시간 계산 + 전날 평균 (초를 시간으로 변환)
@app.get("/get_sleep_info")
def get_sleep_time():
    query_datetime = convert_utc_to_kst()
    query_date = datetime.strptime(query_datetime, "%Y-%m-%d %H:%M:%S").date()

    # 오늘 총 휴식 시간 (초를 시간으로 변환)
    current = fetch_data("""
        SELECT COALESCE(SUM(home_data), 0) / 3600 AS total 
        FROM behavior_log 
        WHERE DATE(timestamp) = %s AND home_data IS NOT NULL
    """, (query_date,))

    # 지난 7일간 하루 평균 휴식 시간 (초를 시간으로 변환)
    start_date = query_date - timedelta(days=7)
    end_date = query_date - timedelta(days=1)
    previous_avg = fetch_data("""
        SELECT ROUND(AVG(daily_total / 3600), 1) AS avg_total FROM (
            SELECT SUM(home_data) AS daily_total
            FROM behavior_log
            WHERE DATE(timestamp) BETWEEN %s AND %s
            AND home_data IS NOT NULL AND home_data > 0
            GROUP BY DATE(timestamp)
        ) AS daily_totals
    """, (start_date, end_date))

    return {
        "total_sleep": round(float(current[0]['total']), 1),
        "prev_avg_sleep": round(float(previous_avg[0]['avg_total'] or 0), 1)
    }
