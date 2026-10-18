// AI 매칭하기(무료판) — 브라우저 안에서 match_index.json 과 비교해 시너지 후보를 찾는다.
// 입력한 매도 희망 정보는 서버로 보내지 않는다. (연결 요청 버튼을 누를 때만 본인이 입력한 내용이 접수된다)
(function () {
  "use strict";
  const HANGUL = /[가-힣]{2,}/g;
  const ALNUM = /(?<![A-Za-z0-9])[A-Z][A-Z0-9&\-]{1,7}(?![A-Za-z0-9])/g;
  const TYPES = {
    h:  { label: "수평 결합", desc: "같은 사업·제품" },
    vb: { label: "수직(후방)", desc: "후보가 사 쓰는 자재·부품을 우리가 만듦" },
    vf: { label: "수직(전방)", desc: "후보가 만드는 제품의 원료·부품을 우리가 씀" },
    cu: { label: "고객 교차", desc: "같은 고객·고객 산업" },
    cap:{ label: "역량 보완", desc: "우리 기술·인증이 후보 사업에 쓰임" },
    sd: { label: "유사 기업", desc: "내가 지목한 회사와 사업이 비슷함" },
    ic: { label: "동일·인접 업종", desc: "DART 업종코드가 같거나 가까움" },
    af: { label: "계열 연결", desc: "지분 관계로 이어진 상장사" }
  };
  const TIERS = {
    1: { label: "1티어", desc: "직접 경쟁·동종 사업" },
    2: { label: "2티어", desc: "밸류체인·인접 업종" },
    3: { label: "3티어", desc: "관련 산업·계열 연결" }
  };
  const WEIGHT = { h: 1.0, v: 0.6, cu: 0.7, cap: 0.5, sd: 0.8 };
  const MIN = { h: 0.15, vb: 0.12, vf: 0.12, cu: 0.09, cap: 0.10, sd: 0.25 };
  const EV_MIN = 3.0;            // 근거 문장으로 인정하는 최소 일치 점수(희소한 단어일수록 큼)

  // 같은 뜻으로 쓰이는 말 (한쪽만 적어도 다른 표현을 쓰는 공시 문장까지 찾는다)
  const SYN = [
    ["초자", "유리", "유리병", "유리용기", "글라스"], ["용기", "병", "패키지", "포장", "포장재", "패키징"],
    ["스포이드", "펌프", "캡", "뚜껑", "디스펜서", "부자재", "병마개"], ["화장품", "뷰티", "코스메틱", "스킨케어", "색조"],
    ["ODM", "OEM", "위탁생산"], ["건강기능식품", "건기식", "영양제"], ["주류", "소주", "맥주", "위스키", "와인"],
    ["제약", "의약품", "바이오", "신약"], ["의료기기", "진단기기"], ["배전반", "수배전반", "분전반", "수변전", "MCC"],
    ["변압기", "트랜스포머"], ["반도체", "웨이퍼", "후공정", "전공정"], ["2차전지", "이차전지", "배터리", "양극재", "음극재"],
    ["전기차", "EV", "자동차부품"], ["로봇", "자동화", "스마트팩토리"], ["데이터센터", "IDC", "클라우드"],
    ["태양광", "신재생", "풍력", "ESS"], ["원전", "원자력", "SMR"], ["건설", "시공", "건축", "토목", "건자재"],
    ["철강", "강관", "후판", "냉연"], ["화학", "소재", "케미칼", "수지"], ["플라스틱", "사출", "성형"],
    ["금형", "몰드", "프레스"], ["물류", "택배", "운송", "풀필먼트"], ["이커머스", "온라인몰", "쇼핑몰", "커머스"],
    ["게임", "콘텐츠", "웹툰", "엔터테인먼트"], ["소프트웨어", "SaaS", "솔루션"], ["AI", "인공지능", "머신러닝"],
    ["방산", "방위산업", "국방"], ["조선", "선박", "해양플랜트"], ["섬유", "의류", "패션", "합섬"],
    ["식품", "가공식품", "제과", "간편식"], ["사료", "축산", "양계"], ["유통", "편의점", "리테일"],
    ["광고", "마케팅", "미디어"], ["환경", "폐기물", "수처리", "재활용"], ["디스플레이", "OLED", "패널"],
    ["통신", "5G", "네트워크"], ["항공", "우주", "위성", "드론"], ["청소", "세정", "클리닝"], ["펫", "반려동물", "애견"],
    ["여행", "관광", "호텔", "리조트"], ["외식", "프랜차이즈", "음식점"], ["교육", "에듀테크", "학원"],
    ["PCB", "인쇄회로기판", "회로기판", "기판"], ["적층", "다층", "빌드업", "MLB"], ["PKG", "패키지", "패키징", "PACKAGE", "SUBSTRATE"],
    ["FC-BGA", "BGA", "FCBGA", "패키지기판", "반도체기판"], ["HDI", "고밀도", "고다층"], ["FPCB", "연성인쇄회로기판", "연성회로"],
    ["소캠", "SOCAMM", "메모리모듈"], ["리드프레임", "LEADFRAME", "반도체패키지"], ["MLCC", "적층세라믹", "수동소자", "인덕터", "저항기"]
  ];
  // 업종 검색: 입력어 → DART(KSIC 10차) 업종명에서 찾을 말
  const ALIAS = {
    "pcb": ["인쇄회로기판"], "hdi": ["인쇄회로기판"], "회로": ["인쇄회로기판", "전자집적회로"], "기판": ["인쇄회로기판", "반도체"],
    "반도체": ["반도체", "전자집적회로"], "패키지": ["반도체", "포장"], "배터리": ["축전지", "일차전지"], "2차전지": ["축전지"], "ess": ["축전지"],
    "화장품": ["화장품"], "용기": ["용기", "포장", "플라스틱"], "유리": ["유리"], "캡": ["플라스틱", "금속"], "병": ["용기", "유리"],
    "배전반": ["배전반"], "변압기": ["변압기"], "전력": ["전기", "배전반", "변압기"], "디스플레이": ["디스플레이", "표시장치"], "oled": ["디스플레이"],
    "자동차": ["자동차"], "전장": ["자동차", "전기"], "제약": ["의약품"], "바이오": ["의약품", "연구개발"], "의료": ["의료"],
    "소프트웨어": ["소프트웨어"], "sw": ["소프트웨어"], "게임": ["게임"], "로봇": ["로봇", "일반 목적용 기계"], "철강": ["철강", "제강", "압연"],
    "건설": ["건설", "건축"], "식품": ["식품", "음료"], "의류": ["의복", "섬유"], "패션": ["의복", "섬유"], "물류": ["운송", "창고"],
    "택배": ["택배", "운송"], "태양광": ["태양", "발전", "전지"], "원전": ["원자력", "발전"], "화학": ["화학"], "플라스틱": ["플라스틱"],
    "금형": ["금형", "주형", "금속"], "led": ["발광", "조명"], "광고": ["광고"], "교육": ["교육"], "여행": ["여행"], "호텔": ["숙박"],
    "외식": ["음식점"], "유통": ["도매", "소매"], "이커머스": ["전자상거래", "소매"], "엔터": ["영화", "방송", "출판"], "방산": ["무기", "항공"],
    "조선": ["선박"], "해운": ["해상"], "항공": ["항공"], "건자재": ["건축", "시멘트"], "통신": ["통신"], "ai": ["소프트웨어", "정보서비스"],
    "클라우드": ["정보서비스", "소프트웨어"], "데이터센터": ["정보서비스"], "장비": ["기계", "장비"], "부품": ["부품"], "소재": ["화학", "금속", "비금속"]
  };
  const GENERIC = /제조업|도매업|소매업|공급업|서비스업|기타|그 외|및|전문|일반|관련|가공|처리업|임대업|제품|용품|부분품/g;
  let IDX = null, CV = null, KSIC = null, KNAME = null, KCOUNT = {}, ICBY = null, CASES = null;

  function tok(text) {
    const out = [];
    (String(text).match(HANGUL) || []).forEach(function (w) { for (let i = 0; i < w.length - 1; i++) out.push(w.substr(i, 2)); });
    (String(text).replace(/[a-z]+/g, function (m) { return m.toUpperCase(); }).match(ALNUM) || []).forEach(function (w) { out.push(w); });
    return out;
  }
  // 입력 문장 + (선택칸 단어, 유사어)를 가중치 맵으로 만든다. 직접 쓴 단어 1.0, 덧붙인 단어 0.6
  function expandTerms(text, bag) {
    const extra = [], low = String(text).toUpperCase();
    SYN.forEach(function (g) {
      if (g.some(function (t) { return low.indexOf(t.toUpperCase()) >= 0; })) g.forEach(function (t) { if (low.indexOf(t.toUpperCase()) < 0) extra.push(t); });
    });
    return extra.concat(bag || []);
  }
  function qvec(text, bag) {
    const cnt = new Map();
    const add = function (t, w) { const i = IDX.vid.get(t); if (i !== undefined) cnt.set(i, (cnt.get(i) || 0) + w); };
    tok(text).forEach(function (t) { add(t, 1); });
    tok(expandTerms(text, bag).join(" ")).forEach(function (t) { add(t, 0.6); });
    const v = new Map(); let s = 0;
    cnt.forEach(function (n, i) { const w = (1 + Math.log(1 + n) - Math.log(2)) * IDX.idf[i]; v.set(i, w); s += w * w; });
    s = Math.sqrt(s) || 1; v.forEach(function (w, i) { v.set(i, w / s); });
    return v;
  }
  function dot(q, c) { if (!q.size || !c.size) return 0; let s = 0; const a = q.size < c.size ? q : c, b = a === q ? c : q; a.forEach(function (w, i) { const x = b.get(i); if (x) s += w * x; }); return s; }
  function arrMap(a) { const m = new Map(); for (let i = 0; i < a.length; i += 2) m.set(a[i], a[i + 1] / 100); return m; }
  function addInto(dst, src, k) { src.forEach(function (w, i) { dst.set(i, (dst.get(i) || 0) + w * k); }); }
  function norm(v) { let s = 0; v.forEach(function (w) { s += w * w; }); s = Math.sqrt(s) || 1; v.forEach(function (w, i) { v.set(i, w / s); }); return v; }

  async function load() {
    if (IDX) return;
    const rs = await Promise.all([fetch("match_index.json?v=" + (window.MATCH_V || "3")), fetch("ksic.json?v=1")]);
    if (!rs[0].ok) throw new Error("색인을 불러오지 못했어요");
    const d = await rs[0].json();
    d.vid = new Map(d.vocab.map(function (t, i) { return [t, i]; }));
    IDX = d;
    CV = d.c.map(function (c) { return { P: arrMap(c.P), M: arrMap(c.M), S: arrMap(c.S) }; });
    ICBY = new Map(d.c.map(function (c) { return [c.c, c.ic || ""]; }));
    if (rs[1].ok) {
      KSIC = await rs[1].json();
      KNAME = new Map(KSIC.c);
      d.c.forEach(function (c) { if (c.ic) for (let n = 2; n <= Math.min(5, c.ic.length); n++) { const k = c.ic.slice(0, n); KCOUNT[k] = (KCOUNT[k] || 0) + 1; } });
    }
  }

  // ── DART 업종(KSIC 10차) ──
  function letterOf(code) { return KSIC && KSIC.sec ? (KSIC.sec[code.slice(0, 2)] || "") : ""; }
  function ksicLabel(code) { return (KNAME && KNAME.get(code) ? KNAME.get(code) : "") + " · " + letterOf(code) + code; }
  function ksicNameOf(code) {      // 정확히 없으면 가장 긴 앞부분 코드의 이름
    if (!KNAME || !code) return "";
    for (let n = code.length; n >= 2; n--) if (KNAME.has(code.slice(0, n))) return KNAME.get(code.slice(0, n));
    return "";
  }
  function searchKsic(q) {
    if (!KSIC) return [];
    q = String(q || "").trim().toLowerCase(); if (!q) return [];
    const terms = [q];
    Object.keys(ALIAS).forEach(function (k) { if (q.indexOf(k) >= 0) ALIAS[k].forEach(function (t) { terms.push(t.toLowerCase()); }); });
    q.split(/\s+/).filter(function (w) { return w.length >= 2 && w !== q; }).forEach(function (w) { terms.push(w); });
    const rows = [], isNum = /^\d+$/.test(q);
    KSIC.c.forEach(function (r) {
      const code = r[0], name = r[1]; if (code.length < 3) return;
      const nl = name.toLowerCase(); let s = 0;
      if (isNum && code.indexOf(q) === 0) s = 6;
      terms.forEach(function (t, i) { if (nl.indexOf(t) >= 0) s += i === 0 ? 4 : 2; });
      if (s > 0) rows.push({ code: code, name: name, n: KCOUNT[code] || 0, s: s, label: ksicLabel(code) });
    });
    rows.sort(function (a, b) { return (b.s - a.s) || (b.n - a.n) || (a.code.length - b.code.length); });
    const live = rows.filter(function (r) { return r.n > 0; });
    return (live.length ? live : rows).slice(0, 14);
  }
  function ksicTerms(sel) {         // 선택한 업종 이름에서 검색에 쓸 단어
    const out = [];
    (sel || []).forEach(function (s) { String(s.name).replace(GENERIC, " ").split(/[\s,·()]+/).forEach(function (w) { if (w.length >= 2) out.push(w); }); });
    return out;
  }
  function pref(a, b) {
    if (!a || !b) return 0;
    const m = Math.min(a.length, b.length); let n = 0;
    while (n < m && a[n] === b[n]) n++;
    return n;
  }
  function maxPref(code, anchors) { let L = 0; (anchors || []).forEach(function (a) { L = Math.max(L, pref(code, a)); }); return L; }

  // 문장과 질의 사이의 일치 점수: 겹치는 토큰의 idf 합 (희소한 단어가 겹칠수록 큼)
  function tokWeights(text, bag) {
    const m = new Map();
    tok(text).forEach(function (t) { m.set(t, 1); });
    tok(expandTerms(text, bag).join(" ")).forEach(function (t) { if (!m.has(t)) m.set(t, 0.6); });
    return m;
  }
  function ovl(sentTokens, qm) {
    let s = 0; const seen = new Set();
    sentTokens.forEach(function (t) {
      if (seen.has(t) || !qm.has(t)) return; seen.add(t);
      const i = IDX.vid.get(t); if (i !== undefined) s += IDX.idf[i] * qm.get(t);
    });
    return s;
  }
  function bestSentences(sents, qm, limit, minv) {
    return sents.map(function (s) { return { s: s, n: ovl(tok(s), qm) }; })
      .filter(function (x) { return x.n >= (minv || EV_MIN); }).sort(function (a, b) { return b.n - a.n; }).slice(0, limit);
  }
  function userQuote(text, sentence) {
    if (!text) return null;
    const sm = new Map(); tok(sentence).forEach(function (t) { sm.set(t, 1); });
    let best = null, bn = 2;
    String(text).split(/[\n;·\/]|\.(?:\s|$)|,\s/).forEach(function (seg) {
      seg = seg.trim(); if (seg.length < 2) return;
      const n = ovl(tok(seg), sm); if (n > bn) { bn = n; best = seg; }
    });
    return best;
  }
  function esc(s) { return String(s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function hi(sentence, text, bag) {
    let h = esc(sentence);
    const ws = Array.from(new Set((String(text).match(/[가-힣A-Za-z0-9&]{2,}/g) || []).concat(expandTerms(text, bag))))
      .filter(function (w) { return h.indexOf(w) >= 0; }).sort(function (a, b) { return b.length - a.length; }).slice(0, 14);
    if (!ws.length) return h;
    const re = new RegExp("(" + ws.map(function (w) { return w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); }).join("|") + ")", "g");
    return h.replace(re, "<mark>$1</mark>");
  }

  // ── 재무 판정 (후보를 없애는 용도가 아니라 '재무 반영 추천 리스트'와 '재무 무관 전체 리스트'를 나누는 용도) ──
  function finCheck(c, inp) {
    const f = c.f, me = (inp && inp.fin) || {}, rev = f[0], op = f[1], eq = f[2], debt = f[3];
    if (rev === null && op === null && eq === null) return { ok: null, why: ["재무 정보 없음(코넥스·미공시)"] };
    const w = [];
    if (op !== null && op < 0) w.push("영업적자");
    if (eq !== null && eq <= 0) w.push("자본잠식");
    else if (eq && debt && debt / eq > 3) w.push("부채비율 " + Math.round(debt / eq * 100) + "%");
    if (me.price && eq && me.price / eq > 0.5) w.push("희망 매각가가 자본의 " + Math.round(me.price / eq * 100) + "%");
    if (me.rev && rev && rev < me.rev) w.push("매출이 매도 기업보다 작음");
    return { ok: w.length === 0, why: w };
  }

  // 입력 → 후보 목록
  function run(inp, opt) {
    const wide = !!(opt && opt.wide), mf = wide ? 0.6 : 1;      // 넓게 보기: 기준을 낮춰 관련도가 낮은 후보까지 포함
    const picked = (inp.industries || []).map(function (s) { return s.code; });
    const pickedC = (inp.custIndustries || []).map(function (s) { return s.code; });
    const bagI = ksicTerms(inp.industries), bagC = ksicTerms(inp.custIndustries);
    const kw = (inp.keywords || "").trim();
    const prodAll = inp.products + (kw ? "\n" + kw : "");
    // 핵심 제품 키워드는 같은 글을 3번 넣어 비중을 키운다. 업종 선택은 보조 신호(비중 낮게)
    let qP = qvec(inp.products + (kw ? "\n" + kw + "\n" + kw + "\n" + kw : ""), []);
    const bagPV = bagI.length ? qvec("", bagI) : new Map(), bagCV = bagC.length ? qvec("", bagC) : new Map();
    const qM = qvec(inp.materials, []), qT = qvec(inp.tech + "\n" + inp.issues, []);
    const qC = qvec(inp.customers, []); addInto(qC, bagCV, 0.45); norm(qC);
    // 1) 지목한 비슷한 회사들의 사업 벡터를 질의에 섞는다
    const seeds = [], seedVec = new Map();
    (inp.similar || "").split(/[,\n]/).map(function (s) { return s.trim(); }).filter(Boolean).forEach(function (nm) {
      let k = IDX.c.findIndex(function (c) { return c.n === nm; });
      if (k < 0) k = IDX.c.findIndex(function (c) { return c.n.indexOf(nm) >= 0; });
      if (k >= 0 && seeds.indexOf(k) < 0) { seeds.push(k); addInto(seedVec, CV[k].P, 1); }
    });
    if (seeds.length) { norm(seedVec); const q2 = new Map(qP); addInto(q2, seedVec, 0.5); qP = norm(q2); }
    // 2) 1차 점수로 상위 회사의 사업 벡터를 섞어 한 번 더 찾는다(표현이 달라도 같은 사업을 찾기 위함)
    const first = IDX.c.map(function (c, k) { return [k, dot(qP, CV[k].P)]; }).sort(function (a, b) { return b[1] - a[1]; }).slice(0, 8);
    if (first[0] && first[0][1] > 0.05) { const avg = new Map(); first.forEach(function (x) { addInto(avg, CV[x[0]].P, 1); }); norm(avg); const q3 = new Map(qP); addInto(q3, avg, 0.35); qP = norm(q3); }
    if (bagPV.size) { const q4 = new Map(qP); addInto(q4, bagPV, 0.25); qP = norm(q4); }

    // 3) 기준 업종(앵커): 직접 고른 업종 + 지목한 회사의 업종. 고른 게 없으면 상위 일치 회사들의 업종으로 자동 추정
    const anchors = picked.slice(); let auto = false;
    seeds.forEach(function (k) { const ic = IDX.c[k].ic; if (ic) anchors.push(ic); });
    if (!picked.length) {
      const cnt = {};
      first.forEach(function (x) { const ic = IDX.c[x[0]].ic; if (ic) { const k = ic.slice(0, Math.min(4, ic.length)); cnt[k] = (cnt[k] || 0) + 1; } });
      Object.keys(cnt).sort(function (a, b) { return cnt[b] - cnt[a]; }).slice(0, 2).forEach(function (k) { if (cnt[k] >= 2) { anchors.push(k); auto = true; } });
    }

    const qmP = tokWeights(prodAll, bagI), qmM = tokWeights(inp.materials, []), qmC = tokWeights(inp.customers, bagC), qmT = tokWeights(inp.tech + "\n" + inp.issues, []);
    // 고객사 이름은 글자 조각이 아니라 이름 전체가 후보 공시 문장에 나올 때만 '같은 고객'으로 친다
    const cnames = (inp.customers || "").split(/[,\n;·\/]|\s및\s|\s등(?:\s|$)/).map(function (s) { return s.trim(); }).filter(function (s) { return s.length >= 2 && s.length <= 20; });
    const cnUp = cnames.map(function (n) { return n.replace(/\s+/g, "").toUpperCase(); });
    function custHits(c, v) {
      const all = (c.e.S || []).concat(c.e.P || []);
      let sub = 0, vec = 0; const sents = [];
      cnUp.forEach(function (nm, j) {
        const sh = all.filter(function (s) { return s.replace(/\s+/g, "").toUpperCase().indexOf(nm) >= 0; });
        if (sh.length) { sub++; sents.push({ s: sh[0], name: cnames[j] }); return; }
        const tk = tok(cnames[j]);
        if (nm.length >= 4 && tk.length >= 3 && tk.every(function (t) { const i = IDX.vid.get(t); return i !== undefined && (v.S.has(i) || v.P.has(i) || v.M.has(i)); })) vec++;
      });
      return { sub: sub, vec: vec, sents: sents };
    }
    // 여러 사업을 하는 회사는 벡터가 퍼져 있어 코사인이 낮아지므로, '내 단어가 얼마나 들어 있나(포함률)'도 함께 본다
    const cov = function (q, c) { let a = 0, b = 0; q.forEach(function (w, i) { b += w; if (c.has(i)) a += w; }); return b ? a / b : 0; };
    const codeScore = function (L) { return L >= 4 ? 0.30 : L === 3 ? 0.16 : L === 2 ? 0.05 : 0; };
    const out = [];
    IDX.c.forEach(function (c, k) {
      const v = CV[k], isSeed = seeds.indexOf(k) >= 0;
      const ch = custHits(c, v);
      const L = maxPref(c.ic || "", anchors), Lc = maxPref(c.ic || "", pickedC);
      const s = { h: dot(qP, v.P) + 0.4 * cov(qP, v.P), vb: dot(qP, v.M) + 0.2 * cov(qP, v.M), vf: dot(qM, v.P) + 0.2 * cov(qM, v.P),
        cu: 0.3 * (dot(qC, v.S) + 0.5 * dot(qC, v.P)) + 0.22 * ch.sub + 0.08 * ch.vec + (Lc >= 4 ? 0.2 : Lc === 3 ? 0.12 : 0),
        cap: dot(qT, v.P), sd: seeds.length ? dot(seedVec, v.P) : 0, ch: ch, L: L };
      const score = WEIGHT.h * s.h + WEIGHT.v * Math.max(s.vb, s.vf) + WEIGHT.cu * s.cu + WEIGHT.cap * s.cap + WEIGHT.sd * s.sd + codeScore(L) + (isSeed ? 0.15 : 0);
      if (score < (wide ? 0.03 : 0.05) && !isSeed) return;
      out.push({ k: k, c: c, s: s, score: score, seed: isSeed });
    });
    out.sort(function (a, b) { return b.score - a.score; });
    window.MNA_MATCH_LAST = out;   // 점검용(개발자 도구에서 점수 확인)
    let res = [];
    const topScore = out.length ? out[0].score : 1;
    for (let i = 0; i < out.length && res.length < (wide ? 260 : 160); i++) {
      const o = out[i], c = o.c, reasons = [];
      const spec = [
        ["h", prodAll, bagI, qmP, c.e.P], ["vb", prodAll, bagI, qmP, c.e.M], ["vf", inp.materials, [], qmM, c.e.P],
        ["cu", inp.customers, bagC, qmC, (c.e.S || []).concat(c.e.P || [])], ["cap", inp.tech + "\n" + inp.issues, [], qmT, c.e.P]
      ];
      spec.forEach(function (sp) {
        const mfe = o.s.L >= 3 ? mf * 0.5 : mf;          // 업종이 가까운 후보는 사업 문장 기준을 낮춰 본다
        const t = sp[0]; if (o.s[t] < MIN[t] * mfe) return;
        if (t === "cu" && !o.s.ch.sub && o.s.cu < 0.14 * mfe) return;   // 고객 이름이 직접 나오지 않으면 점수가 충분히 높을 때만
        if (t === "cu" && o.s.ch.sents.length) {         // 고객 이름이 직접 나온 문장을 우선 근거로
          reasons.push({ t: t, ev: o.s.ch.sents.slice(0, 2).map(function (x) { return { co: hi(x.s, x.name, []), me: x.name }; }), val: o.s[t] });
          return;
        }
        const ev = bestSentences(sp[4] || [], sp[3], 2, wide ? EV_MIN * 0.67 : EV_MIN);
        if (!ev.length) return;                       // 근거 문장이 없는 유형은 이유로 쓰지 않는다
        reasons.push({ t: t, ev: ev.map(function (e) { return { co: hi(e.s, sp[1], sp[2]), me: userQuote(sp[1], e.s) }; }), val: o.s[t] });
      });
      if (o.s.sd >= MIN.sd && seeds.length) reasons.push({ t: "sd", ev: [], val: o.s.sd });
      // 업종코드가 같거나 가까우면 DART 업종 자체를 근거로 쓴다 (사업 문장이 달라도 놓치지 않기 위함)
      if (c.ic && (o.s.L >= 4 || (o.s.L === 3 && (reasons.length || o.score / topScore >= (wide ? 0.08 : 0.15))))) {
        const an = anchors.filter(function (a) { return pref(c.ic, a) === o.s.L; })[0] || anchors[0];
        reasons.push({ t: "ic", val: 0.1 * o.s.L, ev: [{ co: "DART 업종 " + esc(ksicLabel(c.ic)) + (o.s.L >= 4 ? " — 기준 업종과 같음" : " — 기준 업종과 인접(같은 소분류)"),
          me: (auto ? "자동 추정 업종 " : "기준 업종 ") + (an ? ksicLabel(an) : "") }] });
      }
      if (!reasons.length && !o.seed) continue;       // 근거가 하나도 없으면 후보에서 제외
      reasons.sort(function (a, b) { return b.val - a.val; });
      res.push({ c: c, score: o.score, reasons: reasons, seed: o.seed, L: o.s.L });
    }
    if (res.length) {
      const top = res[0].score;
      res = res.filter(function (r) { return r.seed || r.L >= 4 || r.reasons.some(function (x) { return x.t === "ic"; }) || r.score / top >= (wide ? 0.1 : 0.2); });
      res.forEach(function (r) {
        const rel = r.score / top, has = function (t) { return r.reasons.some(function (x) { return x.t === t; }); };
        const hasText = has("h"), other = has("vb") || has("vf") || has("cap") || has("sd") || (has("cu") && r.reasons.some(function (x) { return x.t === "cu" && x.val >= 0.2; }));
        r.tier = (hasText && (r.L >= 4 || rel >= 0.55)) || r.L === 5 ? 1 : (hasText || other || r.L >= 4 ? 2 : 3);
        r.grade = rel >= 0.6 ? "상" : (rel >= 0.35 ? "중" : "하");
      });
      // 계열 연결: 상위 후보와 지분으로 이어진 상장사를 3티어로 덧붙인다 (예: 모회사·자회사·관계사)
      const have = new Set(res.map(function (r) { return r.c.c; }));
      const idxBy = new Map(IDX.c.map(function (c) { return [c.c, c]; }));
      const add = [];
      res.slice(0, 40).forEach(function (r) {
        if (r.tier > 2 || !r.c.af) return;
        r.c.af.forEach(function (e) {
          const o2 = idxBy.get(e[0]); if (!o2 || have.has(o2.c)) return;
          have.add(o2.c);
          add.push({ c: o2, score: r.score * 0.35, tier: 3, grade: "하", seed: false, L: maxPref(o2.ic || "", anchors),
            reasons: [{ t: "af", val: 0.2, ev: [{ co: esc(r.c.n) + "의 " + esc(e[1]) + ": <b>" + esc(o2.n) + "</b> (지분 " + e[2] + "%, DART 공시 기준)", me: null }] }] });
        });
      });
      res = res.concat(add);
      res.forEach(function (r) { r.fin = finCheck(r.c, inp); });
      res.sort(function (a, b) { return (a.tier - b.tier) || (b.score - a.score); });
    }
    res.anchors = anchors; res.auto = auto; res.qmP = qmP;
    return res;
  }

  function pct(a, b) { return a !== null && b ? Math.round(a / b * 1000) / 10 : null; }
  // 확인 필요 박스 (후보 선정에는 쓰지 않고 참고·경고로만 표시)
  function checks(c, inp) {
    const f = c.f, out = [];
    const rev = f[0], op = f[1], eq = f[2], debt = f[3];
    const me = inp.fin || {};
    if (op !== null && op < 0) out.push(["warn", "후보의 2025 영업이익이 적자예요 (" + op.toLocaleString() + "억원)"]);
    if (eq !== null && eq <= 0) out.push(["warn", "자본총계 0 이하 — 자본잠식 가능성"]);
    else if (eq && debt && debt / eq > 3) out.push(["warn", "부채비율 " + Math.round(debt / eq * 100) + "% — 재무 부담 확인"]);
    if (/홀딩스|지주|Holdings|HOLDINGS/.test(c.n)) out.push(["info", "지주사 — 실제 사업은 자회사에서 할 수 있어요. 자회사·계열사 사업을 확인하세요"]);
    if (c.h && c.h.length) out.push(["info", "최대주주: " + c.h.slice(0, 2).map(function (x) { return x[0] + " " + x[1] + "%"; }).join(", ") + " (DART)"]);
    if (c.sub && c.sub.length) out.push(["info", "종속회사(출자 50% 초과): " + c.sub.slice(0, 8).join(", ")]);
    else out.push(["info", "최대주주·계열·같은 사업의 계열사 보유 여부는 DART 공시로 확인이 필요해요"]);
    if (me.rev && rev) { const r = rev / me.rev; if (r > 50) out.push(["info", "매도 기업 매출의 약 " + Math.round(r) + "배 규모 — 소규모 딜에 관심이 낮을 수 있어요"]); else if (r < 1) out.push(["warn", "매도 기업보다 매출이 작아요 — 인수 여력 확인"]); }
    if (me.price && eq) { const p = me.price / eq * 100; out.push([p > 50 ? "warn" : "info", "희망 매각가는 후보 자본총계의 약 " + (p < 1 ? p.toFixed(1) : Math.round(p)) + "%"]); }
    if (me.op !== undefined && me.op !== null && me.rev && rev && op !== null) {
      const a = pct(me.op, me.rev), b = pct(op, rev);
      if (a !== null && b !== null) out.push(["info", "영업이익률: 매도 기업 " + a + "% vs 후보 " + b + "%"]);
    }
    if (c.m === "코넥스") out.push(["info", "코넥스 상장사"]);
    if (c.a[0] > 0) out.push(["ok", "최근 5년 타법인 인수 공시 " + c.a[0] + "건 (최근 " + c.a[1].replace(/(\d{4})(\d\d)(\d\d)/, "$1-$2-$3") + ")"]);
    else out.push(["info", "최근 5년 타법인 인수 공시 없음"]);
    return out;
  }
  function won(v) { return v === null || v === undefined || v === "" ? "-" : Number(v).toLocaleString(undefined, { maximumFractionDigits: 1 }); }

  // ── 업계 M&A 사례 (최근 5년 상장사의 타법인 취득 공시) ──
  async function loadCases() {
    if (CASES !== null) return CASES;
    try {
      const r = await fetch("ma_cases.json?v=" + Date.now());
      if (!r.ok) throw new Error("none");
      const d = await r.json(); CASES = d.cases || [];
    } catch (e) { CASES = []; }
    return CASES;
  }
  // 같은 업종 회사가 인수했거나(인수사 업종), 대상 회사 사업 설명이 내 제품과 겹치는 사례
  function relatedCases(res, inp) {
    const anchors = res.anchors || [], qm = res.qmP || new Map();
    const out = [];
    (CASES || []).forEach(function (c) {
      const L = maxPref(ICBY.get(c.bc) || "", anchors);
      const sc = ovl(tok((c.t || "") + " " + (c.tb || "") + " " + (c.p || "")), qm);
      const byBuyer = L >= 3, byTarget = sc >= EV_MIN;
      if (byBuyer || byTarget) out.push({ c: c, byBuyer: byBuyer, byTarget: byTarget, w: (byTarget ? 2 : 0) + (L >= 4 ? 1 : byBuyer ? 0.5 : 0) });
    });
    out.sort(function (a, b) { return (b.c.d > a.c.d ? 1 : b.c.d < a.c.d ? -1 : 0); });
    return out;
  }

  window.MNA_MATCH = { load: load, run: run, checks: checks, finCheck: finCheck, TYPES: TYPES, TIERS: TIERS, esc: esc, won: won, pct: pct,
    searchKsic: searchKsic, ksicLabel: ksicLabel, ksicNameOf: ksicNameOf, loadCases: loadCases, relatedCases: relatedCases,
    names: function () { return IDX ? IDX.c.map(function (c) { return { n: c.n, c: c.c, m: c.m }; }) : []; },
    count: function () { return IDX ? IDX.c.length : 0; }, built: function () { return IDX ? IDX.built : ""; } };
})();
