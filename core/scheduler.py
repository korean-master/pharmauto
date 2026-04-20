"""예약 자동 주문 스케줄러."""

import json
import os
import threading
from datetime import datetime

from PyQt6.QtCore import QThread, QTimer, pyqtSignal

from core import paths


def _load_settings():
    with open(paths.settings_path(), "r", encoding="utf-8") as f:
        return json.load(f)


class OrderScheduler(QThread):
    """예약 시간에 자동 주문을 실행하는 백그라운드 스레드.

    Signals:
        order_started: 주문 시작 알림
        order_progress(str): 진행 메시지
        order_finished(list): 주문 결과
        order_error(str): 에러
        unconfigured_drugs(list): 미설정 약품 목록
    """
    order_started = pyqtSignal()
    order_progress = pyqtSignal(str)
    order_finished = pyqtSignal(list, list)  # (results, retry_results)
    order_error = pyqtSignal(str)
    unconfigured_drugs = pyqtSignal(list)
    oversize_confirm = pyqtSignal(list)  # 4배 초과 약품 확인 요청

    def __init__(self):
        super().__init__()
        self._timer = None
        self._running = True
        self._stop_event = threading.Event()
        self._executed_today = set()  # 오늘 이미 실행한 시간들
        self._oversize_event = threading.Event()
        self._oversize_choices = {}  # UI에서 응답받을 딕셔너리

    def run(self):
        """1분마다 예약 시간 체크."""
        while self._running:
            try:
                self._check_schedule()
            except Exception as e:
                print(f"[스케줄러] 오류: {e}")
            # 1초 단위로 끊어서 대기 — stop() 호출 시 빠르게 종료
            for _ in range(60):
                if not self._running:
                    return
                self._stop_event.wait(1)

    def stop(self):
        self._running = False
        self._stop_event.set()

    def set_oversize_choices(self, choices: dict):
        """UI에서 사용자 선택 결과를 전달받는다.

        Args:
            choices: {insurance_code: pack_size(int)} — 사용자가 선택한 규격
        """
        self._oversize_choices = choices
        self._oversize_event.set()

    @staticmethod
    def _get_unit_options(insurance_code: str) -> list[int]:
        """약품 규격 목록을 캐시에서 조회."""
        data_dir = paths.get_data_dir()

        cache_path = os.path.join(data_dir, "unit_cache.json")
        if os.path.exists(cache_path):
            with open(cache_path, "r", encoding="utf-8") as f:
                cache = json.load(f)
            if insurance_code in cache:
                return sorted(cache[insurance_code])

        prefs_path = os.path.join(data_dir, "drug_preferences.json")
        if os.path.exists(prefs_path):
            with open(prefs_path, "r", encoding="utf-8") as f:
                prefs = json.load(f)
            entry = prefs.get(insurance_code, {})
            if entry.get("unit_options"):
                return sorted(entry["unit_options"])

        return []

    def _check_schedule(self):
        settings = _load_settings()
        if not settings.get("schedule_enabled", False):
            return

        mode = settings.get("schedule_mode", "multiple")
        now = datetime.now()
        current_time = now.strftime("%H:%M")
        today = now.strftime("%Y-%m-%d")

        # 날짜가 바뀌면 실행 기록 초기화
        for key in list(self._executed_today):
            if not key.startswith(today):
                self._executed_today.discard(key)

        if mode == "once":
            # 일 1회: 단일 시간, 하루 전체 처방
            sched_time = settings.get("schedule_once_time", "18:30")
            key = f"{today}_{sched_time}"
            if key not in self._executed_today and current_time == sched_time:
                self._executed_today.add(key)
                self._execute_scheduled_order(settings, "", "")
        else:
            # 일 2회+: 시간대별 분리
            schedule_times = settings.get("schedule_multi_times",
                                          settings.get("order_schedule_times", []))
            if not schedule_times:
                return

            # enabled된 시간만 추출하고 정렬
            enabled_times = []
            for item in schedule_times:
                if isinstance(item, dict):
                    if not item.get("enabled", True):
                        continue
                    enabled_times.append(item.get("time", ""))
                else:
                    enabled_times.append(item)
            enabled_times.sort()

            for item in schedule_times:
                if isinstance(item, dict):
                    sched_time = item.get("time", "")
                    if not item.get("enabled", True):
                        continue
                else:
                    sched_time = item

                key = f"{today}_{sched_time}"
                if key in self._executed_today:
                    continue
                if current_time == sched_time:
                    self._executed_today.add(key)
                    # 이전 시간 ~ 현재 시간
                    idx = enabled_times.index(sched_time) if sched_time in enabled_times else 0
                    start = enabled_times[idx - 1].replace(":", "") if idx > 0 else "0900"
                    end = sched_time.replace(":", "")
                    self._execute_scheduled_order(settings, start, end)

    # ────── 예약 주문 실행 ──────

    def _execute_scheduled_order(self, settings: dict,
                                start_time: str = "", end_time: str = ""):
        """예약 자동 주문 실행.

        흐름:
          1) 처방 조회 → 주문 아이템 수집
          2) 일반 아이템 → 즉시 주문
          3) 규격확인 필요 아이템 → UI에 확인 요청 → 응답 시 별도 주문
        """
        self.order_started.emit()
        time_label = (
            f"{start_time[:2]}:{start_time[2:]}~{end_time[:2]}:{end_time[2:]}"
            if start_time and end_time else "하루 전체"
        )
        self.order_progress.emit(f"예약 자동 주문 시작... ({time_label})")

        try:
            configured_items, unconfigured = self._collect_order_items(
                settings, start_time, end_time
            )

            if unconfigured:
                self.unconfigured_drugs.emit(unconfigured)

            if not configured_items:
                self.order_progress.emit("주문할 약품 없음")
                self.order_finished.emit([], [])
                return

            # ── 일반 / 규격확인 분리 ──
            normal_items, oversize_items = self._split_oversize(configured_items)

            all_results = []
            all_retry = []

            # ── Phase 1: 일반 아이템 즉시 주문 ──
            if normal_items:
                results, retry = self._place_and_update(normal_items, settings)
                all_results.extend(results)
                all_retry.extend(retry)

            # ── Phase 2: 규격확인 필요 아이템 → UI 확인 → 별도 주문 ──
            if oversize_items:
                oversize_results, oversize_retry = self._handle_oversize_order(
                    oversize_items, settings
                )
                all_results.extend(oversize_results)
                all_retry.extend(oversize_retry)

            # 알림 발송
            from core.notification import send_order_complete_notification
            send_order_complete_notification(all_results)

            self.order_finished.emit(all_results, all_retry)

        except Exception as e:
            self.order_error.emit(str(e))

    # ────── 주문 아이템 수집 ──────

    def _collect_order_items(self, settings: dict,
                             start_time: str, end_time: str
                             ) -> tuple[list[dict], list[dict]]:
        """처방 데이터를 조회하고 주문 아이템 / 미설정 약품으로 분류한다."""
        from core.db_reader import fetch_prescriptions
        from core.drug_api import get_drug_name
        from core.inventory import calc_order_qty, get_drug_config, is_configured

        prescriptions = (
            fetch_prescriptions(start_time=start_time, end_time=end_time)
            if start_time and end_time
            else fetch_prescriptions("all")
        )

        # 제외 약품 필터링
        exc_path = paths.exclusions_path()
        exclusions = {}
        if os.path.exists(exc_path):
            with open(exc_path, "r", encoding="utf-8") as f:
                exclusions = json.load(f)

        now = datetime.now()
        filtered = []
        for rx in prescriptions:
            code = rx["insurance_code"]
            exc = exclusions.get(code)
            if exc:
                until = exc.get("exclude_until")
                if until == "permanent":
                    continue
                if until and datetime.strptime(until, "%Y-%m-%d") > now:
                    continue
            filtered.append(rx)

        unconfigured = []
        configured = []
        default_ws = settings.get("default_wholesaler", "geo")

        for rx in filtered:
            code = rx["insurance_code"]
            drug_name = get_drug_name(code)

            if not is_configured(code):
                unconfigured.append({
                    "insurance_code": code,
                    "drug_name": drug_name,
                    "qty": rx["total_qty"],
                })
                continue

            order_qty = calc_order_qty(code, rx["total_qty"])
            if order_qty <= 0:
                continue

            cfg = get_drug_config(code)
            configured.append({
                "insurance_code": code,
                "drug_name": drug_name,
                "spec": "",
                "qty": order_qty,
                "preferred_unit": cfg.get("preferred_unit", 0) if cfg else 0,
                "wholesaler_id": default_ws,
            })

        return configured, unconfigured

    # ────── 일반 / 규격확인 분리 ──────

    OVERSIZE_RATIO = 4

    def _split_oversize(self, items: list[dict]
                        ) -> tuple[list[dict], list[dict]]:
        """선호규격 4배 이상인 아이템을 분리한다."""
        normal = []
        oversize = []
        for item in items:
            pref = item.get("preferred_unit", 0)
            if pref and item["qty"] >= pref * self.OVERSIZE_RATIO:
                units = self._get_unit_options(item["insurance_code"])
                oversize.append({**item, "unit_options": units})
            else:
                normal.append(item)
        return normal, oversize

    # ────── 규격확인 아이템 처리 ──────

    def _handle_oversize_order(self, oversize_items: list[dict],
                               settings: dict) -> tuple[list[dict], list[dict]]:
        """UI에 규격 확인을 요청하고, 응답이 오면 별도 주문한다."""
        oversize_codes = [it["drug_name"] for it in oversize_items]
        self.order_progress.emit(
            f"규격 확인 대기 중: {', '.join(oversize_codes)}"
        )

        self._oversize_event.clear()
        self._oversize_choices = {}
        self.oversize_confirm.emit(oversize_items)

        # 최대 5분 대기
        responded = self._oversize_event.wait(timeout=300)

        if not responded:
            self.order_progress.emit(
                f"규격 미선택 — {len(oversize_items)}건 주문 보류"
            )
            return [], []

        # 사용자 선택 반영
        for item in oversize_items:
            code = item["insurance_code"]
            if code in self._oversize_choices:
                item["preferred_unit"] = self._oversize_choices[code]
            item.pop("unit_options", None)

        self.order_progress.emit(
            f"규격 확인 완료 — {len(oversize_items)}건 추가 주문 중..."
        )
        return self._place_and_update(oversize_items, settings)

    # ────── 주문 실행 + 재고 업데이트 (공통) ──────

    def _place_and_update(self, items: list[dict],
                          settings: dict) -> list[dict]:
        """주문 실행 → 품절 재주문 → 재고 업데이트 → 결과 반환."""
        from core.inventory import update_stock_after_order
        from core.order_engine import is_cart_only_mode, place_orders

        cart_only = is_cart_only_mode()
        mode_text = "장바구니 담기" if cart_only else "자동 주문"
        self.order_progress.emit(f"{len(items)}개 약품 {mode_text} 중...")

        results, retry_results = place_orders(
            items,
            progress_callback=lambda msg: self.order_progress.emit(msg),
            dry_run=cart_only,
        )

        def _update_stock(item):
            code = item.get("insurance_code", "")
            pack_size = item.get("pack_size", 0)
            box_qty = item.get("box_qty", 0)
            if pack_size and box_qty:
                actual_qty = box_qty * pack_size
            else:
                actual_qty = item.get("qty", 0)
            if code and actual_qty > 0:
                update_stock_after_order(code, actual_qty)

        for r in results:
            for item in r.get("success_items", []):
                _update_stock(item)

        # 품절 재주문 성공한 아이템도 재고 반영
        for rr in retry_results:
            if rr.get("success"):
                _update_stock(rr["item"])

        # 품절 재주문 요약 로그
        if retry_results:
            ok = sum(1 for rr in retry_results if rr.get("success"))
            fail = len(retry_results) - ok
            self.order_progress.emit(
                f"품절 재주문: 성공 {ok}건 / 실패 {fail}건"
            )

        return results, retry_results
