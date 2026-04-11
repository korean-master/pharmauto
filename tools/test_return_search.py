"""반품 통합 검색 테스트 -로컬 + 3개 도매상."""

import os
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)


def main():
    from core.return_engine import search_all_sources

    drug_name = "자누메트"
    lot_number = "y006965"

    print(f"약품명: {drug_name}")
    print(f"로트번호: {lot_number}")
    print("=" * 60)

    results = search_all_sources(
        drug_name,
        lot_number,
        progress_callback=lambda msg: print(f"  [{msg}]"),
    )

    print(f"\n{'='*60}")
    print(f"  통합 결과: {len(results)}건")
    print(f"{'='*60}")

    matched = [r for r in results if r.get("matched")]
    unmatched = [r for r in results if not r.get("matched")]

    if matched:
        print(f"\n  === 로트번호 매칭됨 ({len(matched)}건) ===")
        for i, r in enumerate(matched):
            print(f"  [{i+1}] {r['source']} -{r['drug_name']}")
            print(f"      도매상: {r['wholesaler_name']}")
            print(f"      주문일: {r.get('order_date', '-')}")
            print(f"      수량: {r.get('qty', '-')}")
            print(f"      로트: {r.get('lot_number', '-')}")
            print(f"      유효기한: {r.get('expiry', '-')}")
    else:
        print("\n  로트번호 매칭된 결과 없음")

    if unmatched:
        print(f"\n  === 미매칭 ({len(unmatched)}건) ===")
        for i, r in enumerate(unmatched[:10]):
            print(f"  [{i+1}] {r['source']} -{r['drug_name'][:30]}")
            print(f"      주문일: {r.get('order_date', '-')} / 로트: {r.get('lot_number', '-')}")


if __name__ == "__main__":
    main()
