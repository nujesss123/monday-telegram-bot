import os
import json
import asyncio
from datetime import datetime, timezone, timedelta
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request, HTTPException
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
MONDAY_API_KEY = os.getenv("MONDAY_API_KEY")
MONDAY_MY_USER_ID = os.getenv("MONDAY_MY_USER_ID", "29084552")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL_SECONDS", "120"))  # 기본 2분

KST = timezone(timedelta(hours=9))

# 이미 전송한 이벤트 ID 추적 (중복 방지)
seen_event_ids: set = set()


# ─── Telegram 전송 ────────────────────────────────────────────────────────────

async def send_telegram(message: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[ERROR] TELEGRAM_BOT_TOKEN 또는 TELEGRAM_CHAT_ID 환경변수가 없습니다.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, json=payload, timeout=10)
        if resp.status_code != 200:
            print(f"[ERROR] Telegram 전송 실패: {resp.text}")


# ─── Monday.com API 폴링 ──────────────────────────────────────────────────────

async def fetch_activity_logs(from_time: str) -> list:
    query = """
    query ($from: ISO8601DateTime!) {
      boards(limit: 100) {
        id
        name
        activity_logs(limit: 30, from: $from) {
          id
          event
          created_at
          data
          user_id
        }
      }
    }
    """
    headers = {
        "Authorization": MONDAY_API_KEY,
        "Content-Type": "application/json",
        "API-Version": "2024-01",
    }
    payload = {"query": query, "variables": {"from": from_time}}

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.monday.com/v2",
            json=payload,
            headers=headers,
            timeout=30,
        )
        if resp.status_code != 200:
            print(f"[ERROR] Monday API 오류: {resp.status_code} {resp.text}")
            return []

        data = resp.json()
        if "errors" in data:
            print(f"[ERROR] Monday API GraphQL 오류: {data['errors']}")
            return []

        boards = data.get("data", {}).get("boards", [])
        events = []
        for board in boards:
            for log in (board.get("activity_logs") or []):
                log["board_name"] = board.get("name", "")
                events.append(log)
        return events


def is_mentioned_me(log: dict) -> bool:
    """create_update 이벤트에서 내 user ID가 포함된 경우만 True"""
    if log.get("event") != "create_update":
        return False
    data_raw = log.get("data") or ""
    if not isinstance(data_raw, str):
        data_raw = json.dumps(data_raw)
    return MONDAY_MY_USER_ID in data_raw


def format_activity_log(log: dict) -> str:
    board_name = log.get("board_name", "알 수 없는 보드")
    created_at = log.get("created_at", "")

    # data 파싱
    data_raw = log.get("data", "{}")
    try:
        data = json.loads(data_raw) if isinstance(data_raw, str) else (data_raw or {})
    except Exception:
        data = {}

    pulse_name = data.get("pulse_name", data.get("item_name", ""))
    group_name = data.get("group_name", "")

    # 시간 → 한국 시간
    time_str = ""
    if created_at:
        try:
            dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            dt_kst = dt.astimezone(KST)
            time_str = dt_kst.strftime("%m/%d %H:%M")
        except Exception:
            time_str = created_at[:16]

    msg = "📋 <b>Monday.com 멘션 알림</b>\n"
    msg += f"🗂 보드: {board_name}\n"
    if group_name:
        msg += f"📁 그룹: {group_name}\n"
    if pulse_name:
        msg += f"📌 아이템: <b>{pulse_name}</b>\n"
    msg += "💬 댓글에서 멘션됨"
    if time_str:
        msg += f"\n🕐 {time_str}"

    return msg


async def polling_loop():
    if not MONDAY_API_KEY:
        print("[INFO] MONDAY_API_KEY 없음 — Webhook 모드만 동작합니다.")
        return

    print(f"[INFO] Monday.com 폴링 시작 (간격: {POLL_INTERVAL}초)")

    # 서버 시작 시점부터 추적 (이전 이벤트 스킵)
    last_check = datetime.now(timezone.utc)

    while True:
        await asyncio.sleep(POLL_INTERVAL)
        try:
            from_time = last_check.strftime("%Y-%m-%dT%H:%M:%SZ")
            new_last_check = datetime.now(timezone.utc)

            logs = await fetch_activity_logs(from_time)

            new_count = 0
            for log in logs:
                log_id = log.get("id")
                if log_id and log_id not in seen_event_ids:
                    seen_event_ids.add(log_id)
                    if not is_mentioned_me(log):
                        continue
                    msg = format_activity_log(log)
                    await send_telegram(msg)
                    new_count += 1
                    await asyncio.sleep(0.3)  # Telegram rate limit 방지

            if new_count:
                print(f"[INFO] {new_count}개 새 이벤트 전송")

            last_check = new_last_check

        except Exception as e:
            print(f"[ERROR] 폴링 오류: {e}")


# ─── Lifespan ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(polling_loop())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="Monday.com → Telegram Bot", lifespan=lifespan)


# ─── Webhook 엔드포인트 (보조용) ──────────────────────────────────────────────

@app.post("/webhook/monday")
async def monday_webhook(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    if "challenge" in body:
        return {"challenge": body["challenge"]}

    event = body.get("event")
    if not event:
        return {"status": "ignored"}

    # Webhook 이벤트도 포맷해서 전송
    event_type = event.get("type", "unknown")
    board_name = event.get("boardName", "")
    pulse_name = event.get("pulseName", "")

    msg = "📋 <b>Monday.com 알림 (Webhook)</b>\n"
    if board_name:
        msg += f"🗂 보드: {board_name}\n"
    if pulse_name:
        msg += f"📌 아이템: <b>{pulse_name}</b>\n"
    msg += f"🔔 이벤트: {event_type}"

    await send_telegram(msg)
    return {"status": "ok"}


@app.get("/")
async def health_check():
    return {"status": "running", "service": "Monday.com → Telegram Bot"}
