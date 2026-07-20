# 원격 도매상 세팅 체크리스트

원격 접속(AnyDesk/TeamViewer/Chrome RDP) 으로 약국 PC 에 들어가 도매상 셀렉터를
수동 주입하는 절차. 내부용 문서.

## 준비물 (작업 시작 전)

- [ ] AnyDesk 접속 확보 (상대방 9자리 번호)
- [ ] 본인 로컬에 PharmAuto 저장소 checkout 돼있음 + Supabase 설정 유효
- [ ] `tools/selector_templates/` 의 두 템플릿 확인 (row_cart_btn / global_cart_btn)
- [ ] 기존 서버 셀렉터 확인: `python tools/inject_selectors.py list`
- [ ] (선택) 대상 도매상이 패턴 A/B 중 뭔지 사전 파악

## 접속 중 흐름 (30~60분)

### 1. 사이트 진입
- 크롬에서 도매상 사이트 접속 → 로그인 → **의약품주문 페이지** 로 이동
- 약품 검색 (가장 범용적인 "타이레놀" 권장)

### 2. 패턴 판별 (A vs B)

**F12 열고 검색 결과 테이블 각 행을 훑어본다:**

- **패턴 A** (행 내부 담기): 각 행 끝에 "담기/추가/주문" 텍스트 버튼 또는 장바구니 아이콘
  - 예: `<tr>...<td><a class="btn-bag">담기</a></td></tr>`
- **패턴 B** (전역 버튼): 행에는 체크박스/수량 input 만, 하단에 "장바구니담기" 큰 버튼 하나
  - 예: 세화
- **애매한 경우**: 자주구매(⭐) 나 좋아요 아이콘이 행에 있는 걸 "담기" 로 착각 주의. 실제로 눌러서 장바구니 담기는 것만 담기 버튼.

### 3. 템플릿 복사

```bash
cp tools/selector_templates/global_cart_btn.json /tmp/my_session.json
# (편한 경로에)
```

패턴 A 면 `row_cart_btn.json`.

### 4. 셀렉터 추출 (F12 → Copy Selector)

각 요소 우클릭 → Copy → **Copy selector** 후 JSON 에 붙여넣기.
단 **복사된 경로를 그대로 쓰지 말고 일반화** 필요:

| 필드 | 추출 방법 | 주의사항 |
|------|----------|----------|
| `search.search_input` | 검색 입력창 inspect | id 있으면 `#id`, 없으면 `input[name='xxx']` |
| `search.search_btn` | 조회 버튼 inspect | 없으면 빈 문자열 (Enter 키로 대체) |
| `table.result_rows` | 결과 테이블 `<tbody>` → `<tr>` inspect | **`tbody tr` 형태로 일반화** (nth-of-type 제거!) |
| `table.cart_btn_in_row` (A) | 행 내부 담기 버튼 inspect | **tr 안쪽 경로만** (예: `td:last-child > a.btn`) |
| `table.global_cart_btn` (B) | 하단 "장바구니담기" 버튼 | 절대 경로 OK (`button:has-text('장바구니담기')` 권장) |
| `table.row_checkbox_in_row` (B) | 행 첫 td 의 체크박스 | `td:first-child > input[type='checkbox']` |
| `table.qty_input_in_row` | 행 안 수량 입력창 | `input[type='text']` 또는 `td.qty > input` |
| `table.cart_rows_sel` | 장바구니 섹션의 각 행 | 없으면 빈 문자열 |

### 5. 컬럼 인덱스 확인

검색 결과 테이블 첫 행에서 `<td>` 를 **왼쪽부터 0번** 으로 세어:
- 약품명이 몇 번째 td → `name_col_idx`
- 보험코드 → `code_col_idx`
- 규격/단위 → `unit_col_idx`
- 재고 → `stock_col_idx`
- 단가 → `price_col_idx`

해당 없는 건 `null` 로 둠.

### 6. 일반화 검증

편집한 JSON 에서 **절대 경로에 nth-of-type(N) 포함 여부** 확인:
- `result_rows` 에 `tr:nth-of-type(1)` 있으면 지워서 `tbody tr` 로 바꿈
- `cart_btn_in_row` / `qty_input_in_row` / `row_checkbox_in_row` 에 **tr 자체 등장 금지** (행 내부 상대)
- `global_cart_btn` 은 전역이라 nth-of-type 있어도 무방하지만 가급적 `button:has-text()` 같은 안정적 형태

### 7. 드라이런 검증

```bash
python tools/inject_selectors.py validate /tmp/my_session.json
```

에러 나오면 해당 필드 수정. "검증 통과" 뜨면 다음 단계.

### 8. 업로드

```bash
python tools/inject_selectors.py upload /tmp/my_session.json
# 확인 메시지 → y
```

업로드 성공 로그 확인.

### 9. 앱 동작 검증

**원격 접속 중인 약국 PC 에서**:

1. PharmAuto 설정 탭 → 해당 도매상 **"재연동"** 버튼 클릭
2. (또는 앱 재시작 시 재연동 자동 감지 팝업 → Yes)
3. 1~2분 안에 ✅ 정상 뱃지 확인
4. 만약 ❌ 나오면 `error_logs` 에 CART_FAIL_DIAG 올라옴 — 셀렉터 다시 확인

### 10. 실주문 스모크 테스트

1. 약국 실제 처방 약품 중 1~2건 선택 (혹은 소량 테스트성)
2. 주문 버튼 클릭 → 해당 도매상 사이트 자동화 관찰
3. 실제로 장바구니에 담기는지 → 주문 확정까지 가는지 확인
4. 담기 후 자동 검증 (DOM diff + AI 시각) 도 통과하는지 로그 확인

## 대상 사이트가 패턴 A/B 둘 다 아닌 경우

### 가능한 유형
- **iframe 내부 담기 버튼** — 현재 미지원 (v1.5.46+ 예정)
- **Shadow DOM / Web Component** — 특수 처리 필요
- **드래그앤드롭 / 특수 이벤트** — 직접 지원 불가 / 수동 셀렉터 한계

이 경우 서버에 셀렉터 업로드 말고 **`feedback_wholesaler_onboarding.md`** 에 케이스 기록 + 해당 도매상에 대한 별도 지원 방안 논의.

## 여러 약국 공통 적용

한 번 셀렉터 업로드 하면 **같은 도메인을 쓰는 모든 약국** 이 자동 혜택 (`wholesaler_selectors` 는 도메인 키로 공유).
따라서 도매상당 1회 세팅 → 이후 새 약국은 앱 설치 후 도매상 추가하면 서버에서 자동 fetch.

## 사이트 리뉴얼 대응

도매상이 사이트 리뉴얼 → DOM fingerprint 불일치 감지 → 사용자 앱에 "재연동 필요" 팝업 → 실제로는 새 DOM 에 안 맞는 셀렉터니 onboarding 실패 → 사용자 연락 →  원격 접속 → 이 체크리스트 반복.
