"""활성화 코드 발급 스크립트 — 개발자용.

사용법:
  python generate_codes.py          → 10개 코드 생성
  python generate_codes.py 5        → 5개 코드 생성
  python generate_codes.py 1 우리약국  → 우리약국용 1개 생성
"""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from core.auth import generate_code, generate_codes


def main():
    count = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 10
    memo = sys.argv[2] if len(sys.argv) > 2 else ""

    if memo:
        # 특정 약국용 코드 1개
        code = generate_code(pharmacy_name=memo)
        print(f"\n  {memo}: {code}\n")
    else:
        # 일괄 생성
        codes = generate_codes(count)
        print(f"\n  활성화 코드 {count}개 생성:\n")
        for i, c in enumerate(codes, 1):
            print(f"  {i:2d}. {c['code']}")
        print()


if __name__ == "__main__":
    main()
