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
    sd: { label: "유사 기업", desc: "내가 지목한 회사와 사업이 비슷함" }
  };
  const WEIGHT = { h: 1.0, v: 0.6, cu: 0.7, cap: 0.5, sd: 0.8 };
  const MIN = { h: 0.15, vb: 0.12, vf: 0.12, cu: 0.09, cap: 0.10, sd: 0.25 };
  const EV_MIN = 3.0;           // 근거 문장으로 인정하는 최소 일치 점수(희소한 단어일수록 큼)

  // 업종·고객 산업 선택칸 (고르면 관련 단어가 검색에 함께 쓰인다)
  const INDUSTRIES = {
    "화장품·뷰티": ["화장품", "뷰티", "코스메틱", "스킨케어", "색조", "화장품용기"],
    "식품·음료": ["식품", "음료", "가공식품", "제과", "간편식", "생수", "탄산수"],
    "주류": ["주류", "소주", "맥주", "위스키", "와인", "병"],
    "건강기능식품": ["건강기능식품", "건기식", "영양제", "홍삼", "프로바이오틱스"],
    "제약·바이오": ["제약", "의약품", "바이오", "신약", "의약"],
    "의료기기·헬스케어": ["의료기기", "진단", "헬스케어", "임플란트"],
    "자동차·부품": ["자동차", "자동차부품", "완성차", "전기차"],
    "2차전지": ["2차전지", "이차전지", "배터리", "양극재", "음극재"],
    "반도체·디스플레이": ["반도체", "웨이퍼", "디스플레이", "OLED", "패널"],
    "전자부품·PCB": ["PCB", "인쇄회로기판", "반도체기판", "패키지기판", "FPCB", "수동소자", "전자부품"],
    "전기·전력·에너지": ["전력", "전기", "배전반", "변압기", "태양광", "신재생", "ESS"],
    "로봇·자동화·기계": ["로봇", "자동화", "스마트팩토리", "기계", "설비"],
    "건설·건자재": ["건설", "시공", "건축", "토목", "건자재"],
    "화학·소재·플라스틱": ["화학", "소재", "플라스틱", "수지", "사출", "케미칼"],
    "패키징·포장": ["용기", "포장", "패키지", "패키징", "포장재", "병마개"],
    "섬유·패션": ["섬유", "의류", "패션", "봉제", "합섬"],
    "유통·이커머스": ["유통", "이커머스", "온라인", "쇼핑몰", "리테일", "플랫폼"],
    "물류·운송": ["물류", "택배", "운송", "풀필먼트"],
    "IT·소프트웨어": ["소프트웨어", "SaaS", "솔루션", "클라우드", "데이터센터", "AI", "인공지능"],
    "게임·콘텐츠·미디어": ["게임", "콘텐츠", "웹툰", "드라마", "엔터테인먼트", "광고"],
    "방산·항공우주": ["방산", "방위산업", "항공", "우주", "위성", "드론"],
    "조선·해양": ["조선", "선박", "해양플랜트"],
    "환경·폐기물": ["환경", "폐기물", "수처리", "재활용"]
  };
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
    // 전자부품·PCB
    ["PCB", "인쇄회로기판", "회로기판", "기판"], ["적층", "다층", "빌드업", "MLB"], ["PKG", "패키지", "패키징", "PACKAGE", "SUBSTRATE"],
    ["FC-BGA", "BGA", "FCBGA", "패키지기판", "반도체기판"], ["HDI", "고밀도", "고다층"], ["FPCB", "연성인쇄회로기판", "연성회로"],
    ["소캠", "SOCAMM", "메모리모듈"], ["리드프레임", "LEADFRAME", "반도체패키지"], ["MLCC", "적층세라믹", "수동소자", "인덕터", "저항기"]
  ];
  let IDX = null, CV = null;

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
    const r = await fetch("match_index.json?v=" + (window.MATCH_V || "2"));
    if (!r.ok) throw new Error("색인을 불러오지 못했어요");
    const d = await r.json();
    d.vid = new Map(d.vocab.map(function (t, i) { return [t, i]; }));
    IDX = d;
    CV = d.c.map(function (c) { return { P: arrMap(c.P), M: arrMap(c.M), S: arrMap(c.S) }; });
  }

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
  function bestSentences(sents, qm, limit) {
    return sents.map(function (s) { return { s: s, n: ovl(tok(s), qm) }; })
      .filter(function (x) { return x.n >= EV_MIN; }).sort(function (a, b) { return b.n - a.n; }).slice(0, limit);
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
  function bagOf(names) { let b = []; (names || []).forEach(function (n) { b = b.concat(INDUSTRIES[n] || []); }); return b; }

  // 입력 → 후보 목록 (최대 80곳)
  function run(inp, opt) {
    const wide = !!(opt && opt.wide), mf = wide ? 0.6 : 1;      // 넓게 보기: 기준을 낮춰 관련도가 낮은 후보까지 포함
    const bagI = bagOf(inp.industries), bagC = bagOf(inp.custIndustries);
    const prodText = inp.products + "\n" + inp.tech;           // 사업을 설명하는 글
    // 업종·고객 산업 선택칸은 보조 신호(비중 낮게). 직접 쓴 제품 설명이 중심이 되게 한다.
    // 핵심 제품 키워드는 같은 글을 3번 넣어 비중을 키운다
    const kw = (inp.keywords || "").trim();
    const prodAll = inp.products + (kw ? "\n" + kw : "");
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
    const out = [];
    IDX.c.forEach(function (c, k) {
      const v = CV[k], isSeed = seeds.indexOf(k) >= 0;
      const ch = custHits(c, v);
      // 여러 사업을 하는 회사는 벡터가 퍼져 있어 코사인이 낮아지므로, '내 단어가 얼마나 들어 있나(포함률)'도 함께 본다
      const cov = function (q, c) { let a = 0, b = 0; q.forEach(function (w, i) { b += w; if (c.has(i)) a += w; }); return b ? a / b : 0; };
      const s = { h: dot(qP, v.P) + 0.4 * cov(qP, v.P), vb: dot(qP, v.M) + 0.2 * cov(qP, v.M), vf: dot(qM, v.P) + 0.2 * cov(qM, v.P), cu: 0.3 * (dot(qC, v.S) + 0.5 * dot(qC, v.P)) + 0.22 * ch.sub + 0.08 * ch.vec, cap: dot(qT, v.P), sd: seeds.length ? dot(seedVec, v.P) : 0 };
      s.ch = ch;
      const score = WEIGHT.h * s.h + WEIGHT.v * Math.max(s.vb, s.vf) + WEIGHT.cu * s.cu + WEIGHT.cap * s.cap + WEIGHT.sd * s.sd + (isSeed ? 0.15 : 0);
      if (score < 0.05 && !isSeed) return;
      out.push({ k: k, c: c, s: s, score: score, seed: isSeed });
    });
    out.sort(function (a, b) { return b.score - a.score; });
    window.MNA_MATCH_LAST = out;   // 점검용(개발자 도구에서 점수 확인)
    let res = [];
    for (let i = 0; i < out.length && res.length < (wide ? 150 : 80); i++) {
      const o = out[i], c = o.c, reasons = [];
      const spec = [
        ["h", prodAll, bagI, qmP, c.e.P], ["vb", prodAll, bagI, qmP, c.e.M], ["vf", inp.materials, [], qmM, c.e.P],
        ["cu", inp.customers, bagC, qmC, (c.e.S || []).concat(c.e.P || [])], ["cap", inp.tech + "\n" + inp.issues, [], qmT, c.e.P]
      ];
      spec.forEach(function (sp) {
        const t = sp[0]; if (o.s[t] < MIN[t] * mf) return;
        if (t === "cu" && !o.s.ch.sub && o.s.cu < 0.14 * mf) return;   // 고객 이름이 직접 나오지 않으면 점수가 충분히 높을 때만
        if (t === "cu" && o.s.ch.sents.length) {         // 고객 이름이 직접 나온 문장을 우선 근거로
          reasons.push({ t: t, ev: o.s.ch.sents.slice(0, 2).map(function (x) { return { co: hi(x.s, x.name, []), me: x.name }; }), val: o.s[t] });
          return;
        }
        const ev = bestSentences(sp[4] || [], sp[3], 2);
        if (!ev.length) return;                       // 근거 문장이 없는 유형은 이유로 쓰지 않는다
        reasons.push({ t: t, ev: ev.map(function (e) { return { co: hi(e.s, sp[1], sp[2]), me: userQuote(sp[1], e.s) }; }), val: o.s[t] });
      });
      if (o.s.sd >= MIN.sd && seeds.length) reasons.push({ t: "sd", ev: [], val: o.s.sd });
      if (!reasons.length && !o.seed) continue;       // 근거가 하나도 없으면 후보에서 제외
      reasons.sort(function (a, b) { return b.val - a.val; });
      res.push({ c: c, score: o.score, reasons: reasons, seed: o.seed });
    }
    if (res.length) {
      const top = res[0].score;
      res = res.filter(function (r) { return r.seed || r.score / top >= (wide ? 0.1 : 0.25); });
      res.forEach(function (r) { const x = r.score / top; r.grade = x >= 0.6 ? "상" : (x >= 0.35 ? "중" : "하"); });
    }
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
    if (c.sub && c.sub.length) out.push(["info", "종속·계열 회사(출자 50% 초과): " + c.sub.slice(0, 8).join(", ")]);
    else out.push(["info", "최대주주·계열·같은 사업의 계열사 보유 여부는 DART 공시로 확인이 필요해요"]);
    if (me.rev && rev) { const r = rev / me.rev; if (r > 50) out.push(["info", "매도 기업 매출의 약 " + Math.round(r) + "배 규모 — 소규모 딜에 관심이 낮을 수 있어요"]); else if (r < 1) out.push(["warn", "매도 기업보다 매출이 작아요 — 인수 여력 확인"]); }
    if (me.price && eq) { const p = me.price / eq * 100; out.push([p > 30 ? "warn" : "info", "희망 매각가는 후보 자본총계의 약 " + (p < 1 ? p.toFixed(1) : Math.round(p)) + "%"]); }
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

  window.MNA_MATCH = { load: load, run: run, checks: checks, TYPES: TYPES, INDUSTRIES: INDUSTRIES, esc: esc, won: won, pct: pct,
    count: function () { return IDX ? IDX.c.length : 0; }, built: function () { return IDX ? IDX.built : ""; } };
})();
