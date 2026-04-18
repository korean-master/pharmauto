/**
 * 도매상 주문 페이지 구조 분석기 (F12 콘솔용)
 *
 * 사용법:
 *  1. 도매상 로그인 → 약품 검색해서 결과가 뜬 상태
 *  2. F12 → Console 탭
 *  3. 이 파일 전체 복사해서 콘솔에 붙여넣기 → Enter
 *  4. 출력된 JSON 전체를 복사해서 Claude에게 전달
 *
 * 민감정보는 수집하지 않음 (URL, 태그, 셀렉터 힌트만)
 */
(() => {
  const MAX = 8;
  const _tag = (el) => el ? `${el.tagName.toLowerCase()}${el.id ? '#' + el.id : ''}${el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\s+/).slice(0, 2).join('.') : ''}` : '';
  const _attrs = (el) => {
    if (!el) return {};
    const out = {};
    ['id', 'name', 'class', 'type', 'value', 'alt', 'src', 'title', 'placeholder', 'href', 'onclick'].forEach(k => {
      const v = el.getAttribute && el.getAttribute(k);
      if (v) out[k] = String(v).slice(0, 100);
    });
    if (el.textContent) {
      const t = el.textContent.trim().slice(0, 40);
      if (t) out.text = t;
    }
    return out;
  };
  const _cssPath = (el) => {
    if (!el || !el.parentElement) return '';
    const parts = [];
    let cur = el;
    while (cur && cur.nodeType === 1 && parts.length < 6) {
      let seg = cur.tagName.toLowerCase();
      if (cur.id) { seg += '#' + cur.id; parts.unshift(seg); break; }
      if (cur.className && typeof cur.className === 'string') {
        const cls = cur.className.trim().split(/\s+/).filter(c => c && !/^\d/.test(c))[0];
        if (cls) seg += '.' + cls;
      }
      const idx = Array.from(cur.parentElement?.children || []).filter(c => c.tagName === cur.tagName).indexOf(cur);
      if (idx >= 0) seg += `:nth-of-type(${idx + 1})`;
      parts.unshift(seg);
      cur = cur.parentElement;
    }
    return parts.join(' > ');
  };

  const report = {
    url: location.href,
    title: document.title,
    lang: document.documentElement.lang || '',
    tables: [],
    buttons_with_text: [],
    inputs: [],
    images_likely_buttons: [],
    cart_indicators: [],
  };

  // 테이블 전체 스캔
  document.querySelectorAll('table').forEach((tbl, ti) => {
    const ths = Array.from(tbl.querySelectorAll('thead th, thead td'))
      .map(h => h.textContent.trim().slice(0, 20));
    const firstTh = ths.length ? ths : Array.from(tbl.querySelectorAll('tr:first-child th, tr:first-child td'))
      .map(h => h.textContent.trim().slice(0, 20));
    const bodyRows = tbl.querySelectorAll('tbody tr, tr');
    const sampleRow = bodyRows[ths.length ? 0 : 1] || bodyRows[0];
    const rowCells = sampleRow ? Array.from(sampleRow.querySelectorAll('td')).map(td => ({
      text: td.textContent.trim().slice(0, 40),
      inner_tags: Array.from(td.children).map(_tag).slice(0, 4),
      has_input: !!td.querySelector('input'),
      has_img: !!td.querySelector('img'),
      has_button: !!td.querySelector('button, a, [onclick]'),
    })) : [];
    report.tables.push({
      idx: ti,
      css: _cssPath(tbl),
      headers: firstTh.slice(0, 20),
      row_count: bodyRows.length,
      first_row_cells: rowCells.slice(0, 20),
    });
  });

  // "담기/장바구니/추가" 텍스트 들어간 모든 인터랙션 요소
  const btnKeywords = ['담기', '장바구니', '추가', '구매', '주문'];
  document.querySelectorAll('button, a, input[type="button"], input[type="submit"], input[type="image"], span[onclick], div[onclick]').forEach(el => {
    const txt = (el.textContent || '').trim().slice(0, 30);
    const val = el.value || '';
    const alt = el.getAttribute('alt') || '';
    const src = el.getAttribute('src') || '';
    const hit = btnKeywords.find(k => txt.includes(k) || val.includes(k) || alt.includes(k));
    if (hit) {
      report.buttons_with_text.push({
        tag: el.tagName.toLowerCase(),
        type: el.getAttribute('type') || '',
        text: txt, value: val, alt, src: src.slice(0, 80),
        css: _cssPath(el),
        in_table_row: !!el.closest('tr'),
        near_qty_input: !!el.closest('tr')?.querySelector('input[type="text"], input[type="number"]'),
      });
    }
  });
  report.buttons_with_text = report.buttons_with_text.slice(0, 30);

  // 수량 input 후보
  document.querySelectorAll('input[type="text"], input[type="number"]').forEach((inp, i) => {
    if (i >= 10) return;
    const row = inp.closest('tr');
    const ph = inp.placeholder || inp.getAttribute('placeholder') || '';
    const nm = inp.name || inp.id || '';
    report.inputs.push({
      css: _cssPath(inp),
      name: nm, placeholder: ph,
      in_row: !!row,
      row_idx: row ? Array.from(row.parentElement.children).indexOf(row) : -1,
    });
  });

  // input[type=image] + 의미있는 img (담기 후보)
  document.querySelectorAll('input[type="image"], a > img, button > img, td:last-child img').forEach((el, i) => {
    if (i >= 20) return;
    const alt = el.getAttribute('alt') || '';
    const src = el.getAttribute('src') || '';
    const parent = el.closest('a, button, input');
    report.images_likely_buttons.push({
      tag: el.tagName.toLowerCase(),
      alt, src: src.slice(0, 100),
      parent_tag: parent ? parent.tagName.toLowerCase() : '',
      css: _cssPath(el),
      in_row: !!el.closest('tr'),
    });
  });

  // 장바구니 카운트 후보 — "장바구니", "카트", "담긴", "N건" 근처 숫자 표시
  const cartKw = ['장바구니', '카트', 'cart', '담긴', '선택'];
  document.querySelectorAll('span, em, strong, b, div, td, a').forEach(el => {
    const t = (el.textContent || '').trim();
    if (t.length > 30 || t.length < 1) return;
    if (cartKw.some(k => t.includes(k) || (el.className && el.className.includes && el.className.includes('cart')))) {
      // 자식 중 숫자만 있는 것
      const nums = t.match(/(\d+)/);
      if (nums) {
        report.cart_indicators.push({
          css: _cssPath(el),
          text: t.slice(0, 40),
          number: nums[1],
        });
      }
    }
  });
  report.cart_indicators = report.cart_indicators.slice(0, 15);

  const json = JSON.stringify(report, null, 2);
  console.log('%c===== 도매상 구조 분석 결과 =====', 'color: #4a9; font-weight: bold;');
  console.log(json);
  console.log('%c↑ 위 JSON 전체를 복사해서 전달하세요', 'color: #4a9;');

  // 클립보드 복사 시도
  try {
    navigator.clipboard.writeText(json).then(
      () => console.log('%c✓ 클립보드에 자동 복사됨', 'color: #4a9; font-weight: bold;'),
      () => console.log('클립보드 자동 복사 실패 — 위 JSON 수동 복사 필요')
    );
  } catch (e) {}
  return report;
})();
