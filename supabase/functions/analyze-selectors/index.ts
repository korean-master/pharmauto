// PharmAuto Edge Function: Claude API 프록시
// DOM 텍스트 분석 + 스크린샷 Vision 분석 겸용
//
// 요청 형식 1 (기존 - DOM only):
//   { site_url, wid, skeleton }
//
// 요청 형식 2 (Vision - 스크린샷 포함):
//   { mode: "vision", prompt, screenshot_b64, dom }

import "jsr:@supabase/functions-js/edge-runtime.d.ts"

const CLAUDE_API_KEY = Deno.env.get("CLAUDE_API_KEY") ?? "";

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
  "Access-Control-Allow-Headers": "Authorization, Content-Type",
};

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") {
    return new Response(null, { headers: CORS_HEADERS });
  }

  if (!CLAUDE_API_KEY) {
    return new Response(
      JSON.stringify({ error: "API key not configured" }),
      { status: 500, headers: { ...CORS_HEADERS, "Content-Type": "application/json" } }
    );
  }

  try {
    const body = await req.json();

    let messages: any[];
    let model: string;
    let maxTokens: number;
    let system: string | undefined;

    if (body.mode === "vision") {
      // ── Vision 모드: 스크린샷 + DOM + 프롬프트 ──
      const { prompt, screenshot_b64, dom, system_prompt } = body;

      if (!prompt || !screenshot_b64) {
        return new Response(
          JSON.stringify({ error: "prompt and screenshot_b64 required" }),
          { status: 400, headers: { ...CORS_HEADERS, "Content-Type": "application/json" } }
        );
      }

      system = system_prompt || undefined;
      model = "claude-haiku-4-5-20251001";
      maxTokens = 1024;

      const content: any[] = [
        {
          type: "image",
          source: {
            type: "base64",
            media_type: "image/png",
            data: screenshot_b64,
          },
        },
        {
          type: "text",
          text: prompt,
        },
      ];

      messages = [{ role: "user", content }];
    } else {
      // ── 기존 모드: DOM skeleton 텍스트 분석 ──
      const { site_url, wid, skeleton } = body;

      if (!skeleton) {
        return new Response(
          JSON.stringify({ error: "skeleton required" }),
          { status: 400, headers: { ...CORS_HEADERS, "Content-Type": "application/json" } }
        );
      }

      model = "claude-haiku-4-5-20251001";
      maxTokens = 512;

      const prompt = `당신은 웹 스크래핑 전문가입니다. 아래는 한국 약품 도매상 사이트(${site_url})의 HTML 폼 요소 목록입니다.

이 사이트에서 약품을 주문하는 자동화 프로그램을 만들어야 합니다.
다음 5가지 요소의 CSS 셀렉터를 찾아주세요:
1. 약품명 또는 보험코드를 입력하는 검색 입력창 (search_input)
2. 검색을 실행하는 검색 버튼 (search_btn)
3. 약품을 장바구니에 담는 담기/추가 버튼 (cart_btn)
4. 주문 수량을 입력하는 필드 (qty_input)
5. 검색 결과가 표시되는 테이블 행 CSS 셀렉터 (result_rows)

반드시 JSON 형식으로만 응답하고, 다른 설명은 절대 포함하지 마세요.
찾을 수 없는 항목은 null로 표시하세요.

응답 형식:
{"search_input": "...", "search_btn": "...", "cart_btn": "...", "qty_input": "...", "result_rows": "..."}

HTML 폼 요소 목록 (${wid}):
${skeleton}`;

      messages = [{ role: "user", content: prompt }];
    }

    // Claude API 호출
    const apiResp = await fetch("https://api.anthropic.com/v1/messages", {
      method: "POST",
      headers: {
        "x-api-key": CLAUDE_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
      },
      body: JSON.stringify({
        model,
        max_tokens: maxTokens,
        ...(system ? { system } : {}),
        messages,
      }),
    });

    if (!apiResp.ok) {
      const errText = await apiResp.text();
      return new Response(
        JSON.stringify({ error: `Claude API error ${apiResp.status}`, detail: errText.slice(0, 200) }),
        { status: 502, headers: { ...CORS_HEADERS, "Content-Type": "application/json" } }
      );
    }

    const apiData = await apiResp.json();
    const result = apiData.content?.[0]?.text ?? "";

    return new Response(
      JSON.stringify({ result }),
      { headers: { ...CORS_HEADERS, "Content-Type": "application/json" } }
    );
  } catch (e) {
    return new Response(
      JSON.stringify({ error: String(e) }),
      { status: 500, headers: { ...CORS_HEADERS, "Content-Type": "application/json" } }
    );
  }
});
