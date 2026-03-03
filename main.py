import os
import httpx
from fastapi import FastAPI, Request, HTTPException
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="Monday.com → Telegram Bot")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


# ─── Telegram 전송 ──────────────────────────────────────────────────────────────

async def send_telegram(message: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[ERROR] TELEGRAM_BOT_TOKEN 또는 TELEGRAM_CHAT_ID 환경변수가 없습니다.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, json=payload, timeout=10)
        if resp.status_code != 200:
            print(f"[ERROR] Telegram 전송 실패: {resp.text}")


# ─── 이벤트 메시지 포맷터 ────────────────────────────────────────────────────────

def format_event(event: dict) -> str:
    event_type = event.get("type", "unknown")
    board_name = event.get("boardName", "알 수 없는 보드")
    pulse_name = event.get("pulseName", "알 수 없는 아이템")
    user_id = event.get("userId", "")
    group_name = event.get("groupName", "")

    header = f"📋 <b>Monday.com 알림</b>\n"
    board_line = f"🗂 보드: {board_name}\n"
    item_line = f"📌 아이템: <b>{pulse_name}</b>\n"
    group_line = f"📁 그룹: {group_name}\n" if group_name else ""

    # 이벤트 유형별 메시지
    if event_type == "create_pulse":
        detail = "✅ 새 아이템이 생성되었습니다."

    elif event_type == "update_column_value":
        col_title = event.get("columnTitle", "")
        new_val = _extract_value(event.get("value", {}))
        prev_val = _extract_value(event.get("previousValue", {}))
        detail = (
            f"✏️ <b>{col_title}</b> 컬럼이 변경되었습니다.\n"
            f"   이전: {prev_val}\n"
            f"   이후: {new_val}"
        )

    elif event_type == "update_name":
        prev_name = event.get("previousValue", {}).get("name", "")
        detail = f"🔄 아이템 이름 변경: {prev_name} → {pulse_name}"

    elif event_type == "create_update":
        body = event.get("body", "")
        detail = f"💬 새 업데이트가 작성되었습니다:\n<i>{body[:300]}</i>"

    elif event_type == "delete_pulse":
        detail = "🗑 아이템이 삭제되었습니다."

    elif event_type == "due_date_changed":
        new_date = event.get("value", {}).get("date", "")
        prev_date = event.get("previousValue", {}).get("date", "")
        detail = (
            f"📅 마감일 변경\n"
            f"   이전: {prev_date or '없음'}\n"
            f"   이후: {new_date or '없음'}"
        )

    elif event_type == "move_pulse_into_board":
        detail = "➡️ 아이템이 보드로 이동되었습니다."

    elif event_type == "change_column_value":
        col_title = event.get("columnTitle", "")
        new_val = _extract_value(event.get("value", {}))
        detail = f"✏️ <b>{col_title}</b> → {new_val}"

    else:
        detail = f"🔔 이벤트: {event_type}"

    user_line = f"\n👤 사용자 ID: {user_id}" if user_id else ""

    return header + board_line + group_line + item_line + detail + user_line


def _extract_value(val: dict) -> str:
    if not val:
        return "없음"
    # 상태(status) 컬럼
    if "label" in val:
        return val["label"].get("text", str(val))
    # 날짜
    if "date" in val:
        return val["date"] or "없음"
    # 텍스트
    if "text" in val:
        return val["text"] or "없음"
    # 숫자
    if "number" in val:
        return str(val["number"])
    # 사람 배정
    if "personsAndTeams" in val:
        persons = val["personsAndTeams"]
        names = [str(p.get("id", "")) for p in persons]
        return ", ".join(names) if names else "없음"
    return str(val)


# ─── 웹훅 엔드포인트 ─────────────────────────────────────────────────────────────

@app.post("/webhook/monday")
async def monday_webhook(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # Monday.com 웹훅 인증 챌린지 응답
    if "challenge" in body:
        return {"challenge": body["challenge"]}

    event = body.get("event")
    if not event:
        return {"status": "ignored", "reason": "no event"}

    message = format_event(event)
    await send_telegram(message)

    return {"status": "ok"}


@app.get("/")
async def health_check():
    return {"status": "running", "service": "Monday.com → Telegram Bot"}
