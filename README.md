# IOTCOSS

아두이노, Raspberry Pi 4, USB 카메라와 Mobius oneM2M을 연결해 자세를 분석하고
스마트 데스크 피드백을 제공하는 프로젝트입니다.

## 시스템 구성

1. Raspberry Pi가 카메라 영상에서 자세 특징을 추출합니다.
2. 로컬에서 정상 자세, 거북목 등의 상태를 판정합니다.
3. 판정 결과를 Mobius CSE에 `m2m:cin`으로 저장합니다.
4. FastAPI 게이트웨이가 세션과 이벤트를 관리하고 AI 분석 결과를 앱에 전달합니다.
5. Arduino가 전달받은 상태에 따라 데스크, 조명, 부저를 제어합니다.

## FastAPI Mobius AI Gateway

### 실행

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
Copy-Item .env.example .env
uvicorn app.main:app --reload
```

- UI: http://localhost:8000
- OpenAPI: http://localhost:8000/docs
- 상태 확인: http://localhost:8000/health

Mobius 설정과 인증정보는 `.env`에서 관리합니다. 저장소에 API 키를 커밋하지 마세요.
앱 이벤트 요청의 `sync_to_mobius`가 `true`이면 Mobius의 `m2m:cin`으로 동기화됩니다.

AI는 기본적으로 외부 서비스 없이 로컬 분석을 사용합니다. OpenAI 연동 시
`AI_PROVIDER=openai`와 `OPENAI_API_KEY`를 설정합니다.

### 앱 API

- `POST /api/v1/sessions`: 세션 생성
- `GET/DELETE /api/v1/sessions/{id}`: 세션 조회/종료
- `POST/GET /api/v1/sessions/{id}/events`: 이벤트 저장/조회
- `POST /api/v1/sessions/{id}/analysis`: 세션 AI 분석
- `WS /api/v1/ws/sessions/{id}`: 실시간 이벤트
- `POST /api/v1/mobius/ingest`: Mobius 알림 수신

## 디렉터리

- `app/`: FastAPI 서버, Mobius 어댑터, 세션/AI 분석, 웹 UI
- `raspberry_pi_codes/`: 카메라 및 자세 분석 코드
- `arduino_codes/`: 데스크와 피드백 장치 코드
- `tests/`: FastAPI 통합 테스트
