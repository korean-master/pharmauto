"""알림 모듈 - 카카오 알림톡 연동."""

import json
import os

import requests

SETTINGS_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "settings.json")


def _load_settings():
    with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def send_kakao_notification(message: str) -> bool:
    """카카오 알림톡을 전송한다."""
    settings = _load_settings()
    api_key = settings.get("kakao_api_key", "")

    if not api_key:
        print("[알림] 카카오 API 키가 설정되지 않았습니다.")
        return False

    # TODO: 실제 카카오 알림톡 API 연동
    print(f"[알림] 카카오 알림톡 전송: {message}")
    return True


def send_order_complete_notification(results: list[dict]):
    """주문 완료 알림을 전송한다."""
    success_count = sum(1 for r in results if r["success"])
    fail_count = len(results) - success_count

    msg = f"[PharmAuto] 주문 처리 완료\n성공: {success_count}건 / 실패: {fail_count}건"
    if fail_count > 0:
        msg += "\n실패 건은 확인이 필요합니다."

    send_kakao_notification(msg)
