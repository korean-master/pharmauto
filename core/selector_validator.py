"""도매상 CSS 셀렉터 보안 검증 모듈.

업로드/다운로드 양방향에서 악성 패턴을 차단한다.
XSS, RCE 등 웹 공격 벡터가 될 수 있는 셀렉터를 사전 차단.

사용 규칙:
- cloud.py → upload_selectors(): 업로드 직전 검증
- cloud.py → fetch_selectors(): 다운로드 직후 검증
- generic.py → _save_selectors(): 로컬 저장 직전 검증
"""

import re

# 차단할 악성 패턴 목록
# nth-child(), :not() 등 정상 CSS 문법은 허용한다.
DANGEROUS_PATTERNS = [
    r"javascript\s*:",          # javascript: 스킴
    r"on\w+\s*=",               # onclick=, onmouseover= 등 JS 이벤트 핸들러
    r"<\s*script",              # <script 태그 삽입
    r"</\s*script",             # </script> 태그
    r"\beval\s*\(",             # eval() 함수 호출
    r"\bfetch\s*\(",            # fetch() 함수 호출
    r"\bXMLHttpRequest\b",      # XMLHttpRequest
    r"document\s*\.\s*cookie",  # 쿠키 탈취
    r"document\s*\.\s*write",   # document.write
    r"window\s*\.\s*location",  # 리다이렉션
    r"import\s*\(",             # dynamic import()
    r"__import__",              # Python 코드 삽입 시도
]

_COMPILED = [re.compile(p, re.IGNORECASE) for p in DANGEROUS_PATTERNS]

# 셀렉터 문자열 최대 길이 (비정상적으로 긴 값 차단)
MAX_SELECTOR_LENGTH = 500


def is_safe_selector(value: str) -> bool:
    """단일 셀렉터 문자열이 안전한지 검사한다.

    정상적인 CSS 가상 클래스(:nth-child, :not 등)는 허용.
    JS 이벤트 핸들러, eval(), fetch() 등 악성 패턴은 차단.

    Returns:
        True이면 안전, False이면 위험(폐기 필요)
    """
    if not isinstance(value, str):
        return True  # 문자열이 아닌 값은 셀렉터가 아님 - 패스
    if len(value) > MAX_SELECTOR_LENGTH:
        return False
    return not any(pattern.search(value) for pattern in _COMPILED)


def validate_selectors(data: dict) -> bool:
    """셀렉터 딕셔너리 전체를 재귀적으로 검증한다.

    중첩 딕셔너리도 모두 검사한다.
    하나라도 위험한 값이 있으면 False 반환 → 전체 폐기.

    Returns:
        True이면 전체 안전, False이면 오염 데이터
    """
    if not isinstance(data, dict):
        return True

    for key, val in data.items():
        if isinstance(val, str):
            if not is_safe_selector(val):
                _log_violation(key, val)
                return False
        elif isinstance(val, dict):
            if not validate_selectors(val):
                return False
        elif isinstance(val, list):
            for item in val:
                if isinstance(item, str) and not is_safe_selector(item):
                    _log_violation(key, item)
                    return False

    return True


def _log_violation(key: str, value: str):
    """보안 위반 발생 시 로그 출력."""
    # 값이 너무 길면 잘라서 표시
    display = value[:80] + "..." if len(value) > 80 else value
    print(f"[보안] 악성 셀렉터 차단 — 키: '{key}', 값: '{display}'")
