# Monday.com → Telegram 알림 봇 설정 가이드

## 전체 흐름
```
Monday.com 이벤트 → Webhook → 이 서버 → Telegram Bot → 내 채팅
```

---

## 1단계: 텔레그램 봇 만들기

1. 텔레그램에서 **@BotFather** 검색 후 채팅 시작
2. `/newbot` 명령어 입력
3. 봇 이름 입력 (예: `My Monday Bot`)
4. 봇 사용자명 입력 (예: `my_monday_notify_bot`, 반드시 `_bot`으로 끝나야 함)
5. 발급된 **토큰** 복사 (예: `1234567890:ABCdef...`)

## 2단계: 채팅 ID 확인하기

봇에게 아무 메시지나 보낸 후, 아래 URL을 브라우저에서 열기:
```
https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
```
응답 JSON에서 `"chat":{"id": 숫자}` 부분의 숫자가 TELEGRAM_CHAT_ID

> 그룹에 봇을 추가하고 싶다면: 그룹에 봇 초대 → 그룹에서 메시지 보내기 → 위 URL에서 chat id 확인 (음수값)

---

## 3단계: Railway에 배포하기

1. [railway.app](https://railway.app) 가입 (GitHub 계정 연동)
2. **New Project** → **Deploy from GitHub repo** 선택
3. 이 폴더를 GitHub에 먼저 올리기:
   ```bash
   cd monday-telegram-bot
   git init
   git add .
   git commit -m "initial commit"
   # GitHub에 새 repo 만들고 push
   ```
4. Railway에서 해당 repo 선택하여 배포
5. **Variables** 탭에서 환경변수 추가:
   - `TELEGRAM_BOT_TOKEN` = 1단계에서 발급받은 토큰
   - `TELEGRAM_CHAT_ID` = 2단계에서 확인한 ID
6. 배포 완료 후 **Settings → Domains**에서 URL 확인 (예: `https://xxx.railway.app`)

### Render 사용 시
- [render.com](https://render.com) → New Web Service → GitHub repo 연결
- Start Command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
- 환경변수 동일하게 설정

---

## 4단계: Monday.com 웹훅 설정

1. Monday.com에서 알림 받을 **보드** 열기
2. 좌측 하단 **Integrations** (통합) 클릭
3. **Webhooks** 검색 → **When any change happens send a webhook** 선택
4. Webhook URL 입력:
   ```
   https://your-app-name.railway.app/webhook/monday
   ```
5. 저장 → 자동으로 인증 챌린지가 처리됨

---

## 5단계: 테스트

Monday.com 보드에서:
- 새 아이템 추가
- 상태(Status) 변경
- 업데이트(코멘트) 작성

→ 텔레그램으로 메시지가 오면 성공!

---

## 로컬 테스트 방법 (선택)

```bash
# 의존성 설치
pip install -r requirements.txt

# .env 파일 생성
cp .env.example .env
# .env 파일 열어서 실제 값 입력

# 서버 실행
uvicorn main:app --reload --port 8000

# 다른 터미널에서 테스트
curl -X POST http://localhost:8000/webhook/monday \
  -H "Content-Type: application/json" \
  -d '{"event": {"type": "create_pulse", "boardName": "테스트 보드", "pulseName": "새 아이템", "userId": 123}}'
```
