# Backend
GCP클라우드에 올라가는 백엔드 코드 파일입니다

![Image]([https://github.com/2025-Capstone-designe/backend/blob/main/assets/api%20%EB%AA%85%EC%84%B8.png](https://github.com/2025-Capstone-designe/backend/blob/main/assets/%EC%8B%9C%EC%8A%A4%ED%85%9C%20%EC%95%84%ED%82%A4%ED%85%8D%EC%B2%98.png))

## 기능
1. 라즈베리파이로부터 받은 시간, 위치, 센서 데이터를 수신
2. 좌표 데이터를 통해 이동 거리 데이터 생성
3. 센서 데이터를 종합해 행동 데이터를 데이터베이스에 저장(시간, x, y, 이동 거리, 식사 o/x, 집 o/x)
4. OpenAI API를 사용해 데이터 기반 케어 솔루션 제공
5. 프론트엔드에 제공하기 위한 API들 제공

##### API 명세
![Image](https://github.com/2025-Capstone-designe/backend/blob/main/assets/api%20%EB%AA%85%EC%84%B8.png)
