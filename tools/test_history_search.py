"""도매상 입고이력 검색 실제 테스트."""

import asyncio
import os
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)


async def test_geo(drug_name: str):
    """지오영 입고이력 검색 테스트."""
    from core.crypto import load_wholesalers_secure
    from wholesalers.jioeyoung import JioeyoungWholesaler

    ws = load_wholesalers_secure()
    config = ws.get("geo", {})
    if not config.get("id"):
        print("지오영 계정 없음, 스킵")
        return

    geo = JioeyoungWholesaler(config)
    geo.set_progress_callback(lambda msg: print(f"  [{msg}]"))

    print(f"\n{'='*50}")
    print(f"  지오영 검색: {drug_name}")
    print(f"{'='*50}")

    results = await geo.search_history_async(drug_name, headless=False)

    if results:
        print(f"\n  === {len(results)}건 발견 ===")
        for i, r in enumerate(results[:10]):
            print(f"  [{i+1}] {r['drug_name']}")
            print(f"      주문일: {r['order_date']} / 수량: {r['qty']} / 규격: {r.get('spec', '')}")
    else:
        print("\n  결과 없음")

    return results


async def test_baekje(drug_name: str):
    """백제약품 입고이력 검색 테스트."""
    from core.crypto import load_wholesalers_secure
    from wholesalers.baekje import BaekjeWholesaler

    ws = load_wholesalers_secure()
    config = ws.get("baekje", {})
    if not config.get("id"):
        print("백제약품 계정 없음, 스킵")
        return

    bj = BaekjeWholesaler(config)
    bj.set_progress_callback(lambda msg: print(f"  [{msg}]"))

    print(f"\n{'='*50}")
    print(f"  백제약품 검색: {drug_name}")
    print(f"{'='*50}")

    results = await bj.search_history_async(drug_name, headless=False)

    if results:
        print(f"\n  === {len(results)}건 발견 ===")
        for i, r in enumerate(results[:10]):
            print(f"  [{i+1}] {r['drug_name']}")
            print(f"      입고일: {r['order_date']} / 수량: {r['qty']} / 규격: {r.get('spec', '')}")
            if r.get("returnable_qty"):
                print(f"      반품가능: {r['returnable_qty']}")
    else:
        print("\n  결과 없음")

    return results


async def main():
    drug_name = "자누메트"  # 50/1000은 검색 결과에서 필터

    geo_results = await test_geo(drug_name)
    baekje_results = await test_baekje(drug_name)

    print(f"\n{'='*50}")
    print(f"  통합 결과")
    print(f"{'='*50}")
    total = (len(geo_results) if geo_results else 0) + (len(baekje_results) if baekje_results else 0)
    print(f"  지오영: {len(geo_results) if geo_results else 0}건")
    print(f"  백제약품: {len(baekje_results) if baekje_results else 0}건")
    print(f"  합계: {total}건")


if __name__ == "__main__":
    asyncio.run(main())
