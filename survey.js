/* 기업가치 간이평가 설문: 질문 정의 + 답변 → DCF 모델 변환 + 업종 추천
 * 금액 입력 단위는 억원, 비율은 % 숫자(18.9 = 18.9%). 엔진(dcf.js)에는 백만원으로 환산해서 넘긴다.
 * 모든 계산은 브라우저 안에서만 이뤄지고 서버로 전송되지 않는다.
 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory(require("./dcf.js"));
  else root.Survey = factory(root.DCF);
})(typeof self !== "undefined" ? self : this, function (DCF) {

  // ── 기본 가정 (모두 판단값이며 결과 화면 '가정 보기'에 그대로 공개된다) ──
  var CONFIG = {
    rf: 0.04385,          // 국고채 10년 (2026.9.7 기준 — 평가 시점 값으로 갱신 필요)
    rfAsOf: "2026-09-07",
    mrp: 0.065,           // 시장위험프리미엄
    defaultBeta: 0.9,     // 업종 베타 데이터가 없을 때
    taxRate: 0.22,        // 지방소득세 포함 (2026년 개정세율 가정, 세무사 확인 필요)
    g: { down: 0.01, base: 0.02, up: 0.025 },
    waccAdj: { down: 0.01, base: 0, up: -0.01 },
    wGordon: 0.5,
    fallbackExit: { down: 6, base: 8, up: 10 },
    midPeriod: 1,
    termCapexRatio: 1
  };

  var GROWTH_PRESETS = {
    stable: { label: "안정형", desc: "성숙 업종, 완만한 성장", down: [0, 1, 1], base: [2, 2, 2], up: [4, 3, 3] },
    normal: { label: "보통", desc: "시장 평균 수준의 성장", down: [0, 2, 2], base: [4, 3, 3], up: [8, 5, 5] },
    growth: { label: "성장형", desc: "신규 수주·시장 확대가 이어짐", down: [3, 3, 3], base: [8, 6, 5], up: [12, 8, 6] }
  };

  function res(x, A) { return typeof x === "function" ? x(A) : x; }
  function num(A, id) { var v = A[id]; return v === undefined || v === "" || v === null ? NaN : Number(v); }
  function n0(A, id) { var v = num(A, id); return isFinite(v) ? v : 0; }
  function curYear(A) {
    var d = A.baseDate ? new Date(A.baseDate) : new Date();
    return d.getUTCFullYear();
  }
  function round1(x) { return Math.round(x * 10) / 10; }

  // ── 질문 ──────────────────────────────────────────────
  function money(id, label, o) { o = o || {}; return Object.assign({ id: id, label: label, type: "num", unit: "억원", step: 0.01 }, o); }
  function pct(id, label, o) { o = o || {}; return Object.assign({ id: id, label: label, type: "num", unit: "%", step: 0.1 }, o); }

  var QUESTIONS = [
    { id: "company", section: "회사 소개", title: "어떤 사업을 하는 회사인가요?",
      desc: "주요 제품·서비스와 고객을 한두 문장으로 적어주세요. 다음 질문에서 비슷한 상장사(피어)를 찾는 데 쓰입니다.",
      docs: [],
      fields: [
        { id: "name", label: "회사명 (선택)", type: "text", opt: true, placeholder: "예: ○○주식회사 — 결과 화면 제목에만 쓰이며 서버로 저장되지 않아요" },
        { id: "biz", label: "주요 사업", type: "textarea", placeholder: "예: 화장품 유리용기를 설계해 외주 공장에서 생산하고, 화장품 ODM·브랜드사에 납품합니다." }
      ] },
    { id: "sector", section: "회사 소개", title: "비슷한 업종은 어느 쪽인가요?",
      desc: "적어주신 사업 내용으로 가까운 업종을 추천했어요. 맞는 업종을 고르면 그 업종의 상장사 EV/EBITDA·PER 배수를 비교 기준으로 씁니다.",
      docs: [], custom: "sector", fields: [{ id: "sector", type: "choice", label: "업종" }] },
    { id: "date", section: "회사 소개", title: "평가 기준일과 매각 예정 지분을 알려주세요.",
      desc: "기준일 이후에 발생할 현금흐름을 현재가치로 계산합니다. 모르시면 오늘 날짜 그대로 두세요.",
      docs: [],
      fields: [
        { id: "baseDate", label: "평가 기준일", type: "date" },
        pct("share", "매각 예정 지분", { def: function () { return 100; }, min: 1, max: 100, hint: "100%가 아니면 결과에서 지분율만큼 환산한 금액도 보여드려요(경영권 프리미엄·할인은 반영하지 않음)." })
      ] },

    { id: "rev", section: "과거 실적", title: "최근 3개 사업연도 매출액을 입력해주세요.",
      desc: "결산 기준 매출액입니다. 아직 확정 전이면 가결산 값을 쓰세요. (12월 결산 법인 기준)",
      docs: ["최근 3개년 재무제표(감사보고서 또는 표준재무제표증명)"],
      where: "손익계산서의 '매출액'",
      fields: [
        money("rev1", function (A) { return (curYear(A) - 3) + "년 매출액" }),
        money("rev2", function (A) { return (curYear(A) - 2) + "년 매출액" }),
        money("rev3", function (A) { return (curYear(A) - 1) + "년 매출액" })
      ] },
    { id: "op", section: "과거 실적", title: "같은 기간 영업이익은 얼마였나요?",
      desc: "적자면 마이너스로 입력하세요.",
      docs: ["최근 3개년 재무제표"], where: "손익계산서의 '영업이익(손실)'",
      fields: [
        money("op1", function (A) { return (curYear(A) - 3) + "년 영업이익" }, { neg: true }),
        money("op2", function (A) { return (curYear(A) - 2) + "년 영업이익" }, { neg: true }),
        money("op3", function (A) { return (curYear(A) - 1) + "년 영업이익" }, { neg: true })
      ] },
    { id: "da", section: "과거 실적", title: "감가상각비(무형자산상각비 포함)는요?",
      desc: "EBITDA(영업이익 + 감가상각비)를 계산하는 데 필요해요. 사용권자산(리스) 상각도 포함해 주세요.",
      docs: ["현금흐름표 또는 주석의 비용 성격별 분류"], where: "현금흐름표 '감가상각비', '무형자산상각비' 합계",
      fields: [
        money("da1", function (A) { return (curYear(A) - 3) + "년 상각비" }, { opt: true }),
        money("da2", function (A) { return (curYear(A) - 2) + "년 상각비" }, { opt: true }),
        money("da3", function (A) { return (curYear(A) - 1) + "년 상각비" }, { opt: true })
      ] },

    { id: "rev_cur", section: "향후 전망", title: function (A) { return curYear(A) + "년(올해) 예상 매출은요?"; },
      desc: "가장 현실적인 값(기본)과, 일이 잘 풀릴 때(낙관)·안 풀릴 때(보수)를 각각 적어주세요. 세 시나리오가 가격 범위가 됩니다.",
      docs: ["올해 월별 매출 또는 부가세 신고서", "수주잔고·계약서"], where: "올해 1~상반기 실적 × 하반기 전망",
      fields: [
        money("rev_cur_down", "보수 시나리오", { chip: "down", def: function (A) { return round1(n0(A, "rev_cur_base") * 0.95); } }),
        money("rev_cur_base", "기본 시나리오", { chip: "base" }),
        money("rev_cur_up", "낙관 시나리오", { chip: "up", def: function (A) { return round1(n0(A, "rev_cur_base") * 1.05); } })
      ], order: ["rev_cur_base", "rev_cur_down", "rev_cur_up"] },
    { id: "rev_next", section: "향후 전망", title: function (A) { return (curYear(A) + 1) + "년(내년) 예상 매출은요?"; },
      desc: "신규 거래처·신제품·단가 변동까지 반영한 예상치를 적어주세요.",
      docs: ["사업계획서", "신규 수주 계약·견적"], where: "경영진 사업계획 또는 확정 수주분",
      fields: [
        money("rev_next_down", "보수 시나리오", { chip: "down", def: function (A) { return round1(n0(A, "rev_next_base") * 0.85); } }),
        money("rev_next_base", "기본 시나리오", { chip: "base" }),
        money("rev_next_up", "낙관 시나리오", { chip: "up", def: function (A) { return round1(n0(A, "rev_next_base") * 1.1); } })
      ], order: ["rev_next_base", "rev_next_down", "rev_next_up"] },
    { id: "growth", section: "향후 전망", title: function (A) { return (curYear(A) + 2) + "년 이후(3~5년차) 성장은 어느 정도로 보세요?"; },
      desc: "내년 이후 3년의 매출 성장 속도입니다. 시나리오별 성장률은 아래 표를 기본으로 쓰고, 결과 화면에서 바꿀 수 있어요.",
      docs: [], custom: "growth", fields: [{ id: "growthPreset", type: "choice", label: "성장 수준" }] },
    { id: "opm", section: "향후 전망", title: "앞으로의 영업이익률(수익성)은 어느 정도로 보세요?",
      desc: "대표 보수 등 정상화 항목을 더하기 전, 장부상 영업이익률입니다. 작년 수준이 기본값으로 채워져 있으니 확인만 해주세요.",
      docs: ["최근 3개년 손익계산서"], where: "영업이익 ÷ 매출액",
      fields: [
        pct("opm_down", "보수 시나리오", { chip: "down", neg: true, def: function (A) { return round1(lastOpm(A) - 2); } }),
        pct("opm_base", "기본 시나리오", { chip: "base", neg: true, def: function (A) { return round1(lastOpm(A)); } }),
        pct("opm_up", "낙관 시나리오", { chip: "up", neg: true, def: function (A) { return round1(lastOpm(A) + 1); } })
      ], order: ["opm_base", "opm_down", "opm_up"] },

    { id: "ceo", section: "이익 정상화", title: "대표님 보수는 인수 후에도 그대로 나갈까요?",
      desc: "인수자는 대표를 전문경영인으로 교체하는 비용만 인정합니다. 시장 연봉을 넘는 부분은 '정상화 이익'에 더해 가치를 높일 수 있어요.",
      docs: ["급여대장 또는 주석의 임원 보수", "원천징수이행상황신고서"], where: "최근 연도 대표 급여+상여 합계",
      fields: [
        money("ceoPay", "대표 연간 보수(급여+상여)", { opt: true }),
        money("ceoReplace", "대표를 대체할 전문경영인 연봉", { opt: true, def: function () { return 1.5; }, hint: "인수자와 가장 많이 다투는 항목이에요. 확신이 없으면 1.5억원으로 시작하세요." })
      ] },
    { id: "family", section: "이익 정상화", title: "인수 후 필요 없어지는 가족·특수관계자 인건비가 있나요?",
      desc: "실제 근무하지 않거나 인수 후 정리될 인원의 연간 보수 합계입니다. 근무 실체가 있으면 넣지 마세요(인수자가 인정하지 않아요).",
      docs: ["급여대장", "4대보험 가입자 명부"], where: "배우자·자녀 등 관련자 보수 합계",
      fields: [money("familyPay", "연간 보수 합계", { opt: true })] },
    { id: "other", section: "이익 정상화", title: "대표 개인 성격의 비용이나 일회성 비용이 있나요?",
      desc: "법인 차량·대표 관련 보험료·접대비 등 개인 성격 비용입니다. 인수자가 확인해야 인정해주는 항목이라 가치 계산에서는 가능성에 따라 일부만 반영해요.",
      docs: ["판매비와관리비 상세", "보험료 내역서"], where: "판관비 상세 중 개인 성격 항목",
      fields: [
        money("otherLast", function (A) { return (curYear(A) - 1) + "년 해당 금액"; }, { opt: true }),
        money("otherFwd", "올해 이후 연간 예상 금액", { opt: true, def: function (A) { return n0(A, "otherLast"); } })
      ] },

    { id: "wc", section: "운전자본·투자", title: "최근 결산 기준 매출채권·재고·매입채무는요?",
      desc: "사업을 돌리는 데 묶이는 돈(운전자본)을 계산합니다. 매출이 늘수록 자금이 더 묶여요.",
      docs: ["최근 결산 재무상태표"], where: "재무상태표 '매출채권(대손충당금 차감)', '재고자산', '매입채무'",
      fields: [
        money("ar", "매출채권", { opt: true }),
        money("inv", "재고자산", { opt: true }),
        money("ap", "매입채무", { opt: true })
      ] },
    { id: "capex", section: "운전자본·투자", title: "앞으로 연간 설비투자는 어느 정도 예상하세요?",
      desc: "기본값은 감가상각비와 같게(현상 유지) 두었어요. 큰 증설 계획이 있으면 늘려서 적어주세요.",
      docs: ["설비투자 계획"], where: "유형자산 취득 계획",
      fields: [
        money("daFwd", "연간 감가상각비 (올해 이후)", { opt: true, def: function (A) { return round1(n0(A, "da3") * 10) / 10; } }),
        money("capex", "연간 설비투자", { opt: true, def: function (A) { return n0(A, "daFwd"); } })
      ] },

    { id: "cash", section: "재무상태", title: "현재 보유 현금과 차입금은 얼마인가요?",
      desc: "기준일에 가장 가까운 잔액을 적어주세요. 가치(EV)에서 지분가치로 넘어갈 때 더하고 뺍니다.",
      docs: ["은행 잔고증명서", "차입금 명세"], where: "현금및현금성자산 + 단기금융상품 / 단기·장기차입금+사채+리스부채",
      fields: [
        money("cash", "현금 및 현금성자산(단기예금 포함)", { opt: true }),
        money("finAssets", "장기예금 등 기타 금융자산", { opt: true }),
        money("debt", "금융차입금(사채·리스부채 포함)", { opt: true })
      ] },
    { id: "liab", section: "재무상태", title: "차입금 외에 빚처럼 취급되는 항목이 있나요?",
      desc: "인수자는 이 금액만큼 대금을 깎아요. 없으면 0으로 두세요.",
      docs: ["퇴직연금·퇴직급여충당부채 내역", "법인세 신고서"], where: "퇴직급여충당부채(확정급여형), 미지급법인세·배당금",
      fields: [
        money("retire", "퇴직급여채무 등(미적립분)", { opt: true }),
        money("taxPayable", "미지급 법인세·배당금 등", { opt: true }),
        money("minCash", "영업에 꼭 필요한 최소 운전현금", { opt: true, hint: "매도자 관점에서는 보통 0으로 둡니다. 인수자가 요구하면 입력하세요." })
      ] },
    { id: "nonop", section: "재무상태", title: "영업과 무관한 자산(부동산 등)이 있나요?",
      desc: "본업에 쓰지 않는 토지·건물·투자자산입니다. 영업가치와 따로 더해서 지분가치에 반영해요.",
      docs: ["등기부등본", "감정평가서 또는 시세 자료", "임대차계약서"], where: "시세(장부가 아님), 관련 임대보증금·담보대출, 처분 시 세금",
      fields: [
        money("nonOpAssets", "비영업자산 시세 합계", { opt: true }),
        money("nonOpLiabs", "관련 부채(임대보증금·담보대출)", { opt: true }),
        money("nonOpTax", "처분 시 예상 세금·비용", { opt: true }),
        { id: "nonOpInclude", label: "지분가치에 반영", type: "toggle", def: function () { return 1; }, hint: "매각 후 대표가 자산을 따로 인수하는 구조면 켜 두세요." }
      ] },

    { id: "cust", section: "위험 요인", title: "매출이 특정 거래처에 얼마나 몰려 있나요?",
      desc: "거래처 집중도가 높을수록 인수자는 높은 수익률을 요구합니다(할인율에 반영).",
      docs: ["거래처별 매출 명세", "세금계산서 합계표"], where: "최근 연도 매출처별 비중",
      fields: [
        pct("top1", "최대 거래처 매출 비중", { min: 0, max: 100 }),
        pct("top3", "상위 3개 거래처 합계 비중", { min: 0, max: 100 })
      ] },
    { id: "ceoDep", section: "위험 요인", title: "대표님 없이도 회사가 돌아가나요?",
      desc: "영업·기술·거래처 관계가 대표 개인에게 얼마나 달려 있는지 골라주세요.",
      docs: [], custom: "choice",
      fields: [{ id: "ceoDep", type: "choice", label: "대표 의존도", opts: [
        { v: "low", label: "낮음", desc: "핵심 인력과 시스템이 있어 대표 공백이 문제되지 않음" },
        { v: "mid", label: "보통", desc: "중요한 거래처·결정은 대표가 하지만 대체 가능" },
        { v: "high", label: "높음", desc: "영업·기술·거래처 관계가 대표 한 사람에게 집중" }
      ] }] },
    { id: "hope", section: "마무리", title: "생각하고 계신 희망 매각가가 있나요? (선택)",
      desc: "지분 100% 기준 금액을 적으시면 평가 결과와 비교해 보여드려요. 없으면 건너뛰세요.",
      docs: [],
      fields: [money("hopePrice", "희망 매각가(지분 100% 기준)", { opt: true })] }
  ];

  function lastOpm(A) {
    var rev = n0(A, "rev3"), op = n0(A, "op3");
    return rev > 0 ? op / rev * 100 : 10;
  }

  // ── 업종 추천 (키워드 점수) ───────────────────────────
  function suggestSectors(text, sectors) {
    var t = String(text || "").toLowerCase().replace(/\s/g, ""); // 띄어쓰기 차이에 영향받지 않도록
    var scored = (sectors || []).map(function (s) {
      var score = 0, hits = [];
      (s.keywords || []).forEach(function (k) {
        var kk = String(k).toLowerCase().replace(/\s/g, "");
        if (kk && t.indexOf(kk) !== -1) { score += kk.length; hits.push(k); } // 긴(구체적인) 키워드일수록 가중
      });
      return { id: s.id, name: s.name, score: score, hits: hits };
    });
    return scored.filter(function (x) { return x.score > 0; }).sort(function (a, b) { return b.score - a.score; });
  }

  // ── 답변 검증 ─────────────────────────────────────────
  function validate(q, A) {
    var msgs = [];
    (q.fields || []).forEach(function (f) {
      if (f.type === "toggle") return;
      var v = A[f.id];
      if (f.type === "text") return;
      if (f.type === "textarea") { if (!v || String(v).trim().length < 4) msgs.push("주요 사업을 간단히 적어주세요."); return; }
      if (f.type === "choice") { if (!v) msgs.push("하나를 선택해주세요."); return; }
      if (f.type === "date") { if (!v || isNaN(new Date(v))) msgs.push("날짜를 선택해주세요."); return; }
      if (f.type === "num") {
        var blank = v === undefined || v === "" || v === null;
        if (blank) { if (!f.opt) msgs.push("'" + res(f.label, A) + "' 값을 입력해주세요. 없으면 0을 입력하세요."); return; }
        var x = Number(v);
        if (!isFinite(x)) { msgs.push(res(f.label, A) + ": 숫자만 입력해주세요."); return; }
        if (x < 0 && !f.neg) msgs.push(res(f.label, A) + ": 0 이상으로 입력해주세요.");
        if (f.max != null && x > f.max) msgs.push(res(f.label, A) + ": " + f.max + " 이하로 입력해주세요.");
        if (f.min != null && x < f.min) msgs.push(res(f.label, A) + ": " + f.min + " 이상으로 입력해주세요.");
      }
    });
    if (q.id === "rev") {
      if (!(n0(A, "rev3") > 0)) msgs.push("가장 최근 연도 매출은 0보다 커야 계산할 수 있어요.");
    }
    if (q.id === "rev_cur" && !(n0(A, "rev_cur_base") > 0)) msgs.push("올해 기본 시나리오 매출은 0보다 커야 해요.");
    if (q.id === "rev_next" && !(n0(A, "rev_next_base") > 0)) msgs.push("내년 기본 시나리오 매출은 0보다 커야 해요.");
    if (q.id === "cust" && n0(A, "top3") < n0(A, "top1")) msgs.push("상위 3개 합계 비중은 최대 거래처 비중보다 작을 수 없어요.");
    return msgs;
  }

  // ── 위험 프리미엄 산출 ────────────────────────────────
  function riskPremiums(A) {
    var rev3 = n0(A, "rev3");
    var size = rev3 < 100 ? 0.04 : rev3 < 500 ? 0.03 : rev3 < 2000 ? 0.02 : 0.01;
    var top1 = n0(A, "top1");
    var cust = top1 >= 60 ? 0.015 : top1 >= 40 ? 0.01 : top1 >= 20 ? 0.005 : 0;
    var ceoDep = { low: 0, mid: 0.0025, high: 0.005 }[A.ceoDep] || 0;
    var op2 = n0(A, "op2"), op3 = n0(A, "op3"), op1 = n0(A, "op1");
    var vol = 0, volWhy = "";
    if (op3 > 0 && (op2 <= 0 || op3 > op2 * 2.5)) { vol = 0.005; volWhy = "직전 연도 대비 이익이 급증해 지속 가능성 확인이 필요"; }
    else if (op1 < 0 || op2 < 0 || op3 < 0) { vol = 0.005; volWhy = "최근 3년 중 영업적자 연도가 있음"; }
    return {
      size: size, cust: cust, ceoDep: ceoDep, vol: vol, volWhy: volWhy,
      specific: cust + ceoDep + vol
    };
  }

  // ── 답변 → 엔진 입력 ──────────────────────────────────
  // sectorStat: { evEbitda:{down,base,up,n,source}, per:{down,base,up,n}, beta }  (없으면 기본값)
  function pick(v, d) { return v === undefined || v === null || v === "" || isNaN(v) ? d : Number(v); }

  // opts: 결과 화면에서 사용자가 직접 바꾼 가정 {rf, taxRate, wGordon, beta, g:{down,base,up}, exit:{down,base,up}, waccAdj:{...}}
  function buildModel(A, sectorStat, opts) {
    opts = opts || {};
    var rf = pick(opts.rf, CONFIG.rf), taxRate = pick(opts.taxRate, CONFIG.taxRate), wGordon = pick(opts.wGordon, CONFIG.wGordon);
    var gCfg = {}, adjCfg = {};
    ["down", "base", "up"].forEach(function (k) {
      gCfg[k] = pick(opts.g && opts.g[k], CONFIG.g[k]);
      adjCfg[k] = pick(opts.waccAdj && opts.waccAdj[k], CONFIG.waccAdj[k]);
    });
    var M = 100; // 억원 → 백만원
    var warnings = [];
    var baseDate = new Date(A.baseDate);
    baseDate = new Date(Date.UTC(baseDate.getUTCFullYear(), baseDate.getUTCMonth(), baseDate.getUTCDate()));
    var stub = DCF.stubFraction(baseDate);

    var rev3 = n0(A, "rev3") * M, op3 = n0(A, "op3") * M, da3 = n0(A, "da3") * M;
    var ebitdaLast = op3 + da3;
    var daFwd = (isFinite(num(A, "daFwd")) ? num(A, "daFwd") : n0(A, "da3")) * M;
    var capex = (isFinite(num(A, "capex")) ? num(A, "capex") : daFwd / M) * M;

    var ar = n0(A, "ar") * M, inv = n0(A, "inv") * M, ap = n0(A, "ap") * M;
    var cashCostLast = rev3 - ebitdaLast;
    var dso = rev3 > 0 ? ar / rev3 * 365 : 60;
    var dio = cashCostLast > 0 ? inv / cashCostLast * 365 : 0;
    var dpo = cashCostLast > 0 ? ap / cashCostLast * 365 : 0;
    var wcDays = {
      down: { dso: dso + 10, dio: dio + 3, dpo: Math.max(0, dpo - 10) },
      base: { dso: dso, dio: dio, dpo: dpo },
      up: { dso: Math.max(0, dso - 5), dio: dio, dpo: dpo }
    };

    var prem = riskPremiums(A);
    var beta = pick(opts.beta, sectorStat && sectorStat.beta ? sectorStat.beta : CONFIG.defaultBeta);
    var w = DCF.buildWacc({ rf: rf, beta: beta, mrp: CONFIG.mrp, size: prem.size, specific: prem.specific, tax: taxRate });

    var ceoExcess = Math.max(0, n0(A, "ceoPay") - n0(A, "ceoReplace")) * M;
    var family = n0(A, "familyPay") * M;
    var fixed = { base: ceoExcess + family, up: ceoExcess + family, down: ceoExcess };
    var ratio = { base: 0.5, up: 1, down: 0 };

    var preset = GROWTH_PRESETS[A.growthPreset] || GROWTH_PRESETS.normal;
    var ev = sectorStat && sectorStat.evEbitda && sectorStat.evEbitda.base ? sectorStat.evEbitda : null;
    var exit = ev ? { down: ev.down, base: ev.base, up: ev.up } : { down: CONFIG.fallbackExit.down, base: CONFIG.fallbackExit.base, up: CONFIG.fallbackExit.up };
    ["down", "base", "up"].forEach(function (k) { exit[k] = pick(opts.exit && opts.exit[k], exit[k]); });

    function scenario(k) {
      var rc = n0(A, "rev_cur_" + k) * M, rn = n0(A, "rev_next_" + k) * M;
      var rev = [rc, rn];
      preset[k].forEach(function (g) { rev.push(rev[rev.length - 1] * (1 + g / 100)); });
      var opm = n0(A, "opm_" + k) / 100;
      var margin = rev.map(function (r) { return opm + (r > 0 ? daFwd / r : 0); });
      return { rev: rev, margin: margin, addbackFixed: fixed[k], uncertainRatio: ratio[k], da: daFwd, capex: capex,
        dso: wcDays[k].dso, dio: wcDays[k].dio, dpo: wcDays[k].dpo,
        wacc: w.applied + adjCfg[k], g: gCfg[k], exit: exit[k], wGordon: wGordon };
    }
    var scenarios = { base: scenario("base"), up: scenario("up"), down: scenario("down") };

    if (!(n0(A, "rev_cur_down") <= n0(A, "rev_cur_base") && n0(A, "rev_cur_base") <= n0(A, "rev_cur_up")))
      warnings.push("올해 매출이 '보수 ≤ 기본 ≤ 낙관' 순서가 아니에요. 입력을 확인해주세요.");
    if (!(n0(A, "rev_next_down") <= n0(A, "rev_next_base") && n0(A, "rev_next_base") <= n0(A, "rev_next_up")))
      warnings.push("내년 매출이 '보수 ≤ 기본 ≤ 낙관' 순서가 아니에요. 입력을 확인해주세요.");
    var g1 = n0(A, "rev_cur_base") > 0 && rev3 > 0 ? n0(A, "rev_cur_base") / n0(A, "rev3") - 1 : 0;
    var g2 = n0(A, "rev_next_base") / Math.max(n0(A, "rev_cur_base"), 1e-9) - 1;
    if (g2 > 0.5) warnings.push("내년 기본 매출이 올해보다 " + Math.round(g2 * 100) + "% 늘어요. 확정 수주나 계약 근거가 있는지 확인이 필요해요.");
    if (g1 > 0.5 && rev3 > 0) warnings.push("올해 기본 매출이 작년보다 " + Math.round(g1 * 100) + "% 늘어요. 근거를 확인해주세요.");

    var bridge = {
      cash: n0(A, "cash") * M, finAssets: n0(A, "finAssets") * M, debt: n0(A, "debt") * M,
      retire: n0(A, "retire") * M, taxPayable: n0(A, "taxPayable") * M, minCash: n0(A, "minCash") * M,
      nonOpAssets: n0(A, "nonOpAssets") * M, nonOpLiabs: n0(A, "nonOpLiabs") * M, nonOpTax: n0(A, "nonOpTax") * M,
      nonOpInclude: A.nonOpInclude === 0 || A.nonOpInclude === false ? 0 : 1
    };

    var common = {
      stub: stub, taxRate: taxRate, mid: CONFIG.midPeriod, termCapexRatio: CONFIG.termCapexRatio,
      actual: { ebitda: ebitdaLast, ar: ar, inv: inv, ap: ap },
      uncertainLast: n0(A, "otherLast") * M, uncertainFwd: (isFinite(num(A, "otherFwd")) ? num(A, "otherFwd") : n0(A, "otherLast")) * M,
      bridge: bridge
    };

    return { common: common, scenarios: scenarios, wacc: w,
      meta: { prem: prem, beta: beta, rf: rf, taxRate: taxRate, wGordon: wGordon, g: gCfg, waccAdj: adjCfg, ceoExcess: ceoExcess, family: family, wcDays: wcDays, exit: exit,
              exitSource: ev ? ev.source || "업종 피어 배수" : "기본 범위(피어 데이터 없음)",
              growth: preset, warnings: warnings, ebitdaLast: ebitdaLast, rev3: rev3, daFwd: daFwd, capex: capex, config: CONFIG } };
  }

  // 배수법 교차검증 (EV/EBITDA, PER). 단위: 백만원
  function multipleChecks(model, sectorStat, A) {
    var c = model.common, b = c.bridge;
    var out = { evEbitda: null, per: null };
    var addback = model.scenarios.base.addbackFixed + model.scenarios.base.uncertainRatio * c.uncertainLast;
    var normLast = c.actual.ebitda + addback;
    var bridgeNet = b.cash + b.finAssets - b.debt - b.retire - b.taxPayable - b.minCash;
    var nonOp = b.nonOpInclude ? (b.nonOpAssets - b.nonOpLiabs - b.nonOpTax) : 0;
    if (sectorStat && sectorStat.evEbitda && sectorStat.evEbitda.base) {
      var m = sectorStat.evEbitda;
      out.evEbitda = { basis: normLast, mult: { down: m.down, base: m.base, up: m.up },
        ev: { down: normLast * m.down, base: normLast * m.base, up: normLast * m.up },
        equity: { down: normLast * m.down + bridgeNet + nonOp, base: normLast * m.base + bridgeNet + nonOp, up: normLast * m.up + bridgeNet + nonOp } };
    }
    if (sectorStat && sectorStat.per && sectorStat.per.base) {
      var p = sectorStat.per;
      var da = model.meta.daFwd;
      var ni = Math.max(0, (normLast - da) * (1 - c.taxRate)); // 무차입 가정(이자·영업외 제외)
      out.per = { basis: ni, mult: { down: p.down, base: p.base, up: p.up },
        equity: { down: ni * p.down + nonOp, base: ni * p.base + nonOp, up: ni * p.up + nonOp } };
    }
    return out;
  }

  return { CONFIG: CONFIG, GROWTH_PRESETS: GROWTH_PRESETS, QUESTIONS: QUESTIONS, res: res,
           suggestSectors: suggestSectors, validate: validate, buildModel: buildModel,
           multipleChecks: multipleChecks, riskPremiums: riskPremiums, curYear: curYear, num: num, n0: n0 };
});
