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
    cu: { label: "고객 교차", desc: "같은 고객·납품처" },
    cap:{ label: "역량 보완", desc: "우리 기술·인증이 후보 사업에 쓰임" }
  };
  const WEIGHT = { h: 1.0, v: 0.6, cu: 0.6, cap: 0.5 };
  const MIN = { h: 0.12, vb: 0.10, vf: 0.10, cu: 0.10, cap: 0.12 };
  let IDX = null, CV = null;       // 색인, 회사별 벡터

  function tok(text) {
    const out = [];
    (String(text).match(HANGUL) || []).forEach(function (w) { for (let i = 0; i < w.length - 1; i++) out.push(w.substr(i, 2)); });
    (String(text).match(ALNUM) || []).forEach(function (w) { out.push(w); });
    return out;
  }
  function qvec(text) {
    const cnt = new Map();
    tok(text).forEach(function (t) { const i = IDX.vid.get(t); if (i !== undefined) cnt.set(i, (cnt.get(i) || 0) + 1); });
    const v = new Map(); let s = 0;
    cnt.forEach(function (n, i) { const w = (1 + Math.log(n)) * IDX.idf[i]; v.set(i, w); s += w * w; });
    s = Math.sqrt(s) || 1; v.forEach(function (w, i) { v.set(i, w / s); });
    return v;
  }
  function dot(q, c) { if (!q.size || !c.size) return 0; let s = 0; const [a, b] = q.size < c.size ? [q, c] : [c, q]; a.forEach(function (w, i) { const x = b.get(i); if (x) s += w * x; }); return s; }
  function arrMap(a) { const m = new Map(); for (let i = 0; i < a.length; i += 2) m.set(a[i], a[i + 1] / 100); return m; }

  async function load() {
    if (IDX) return;
    const r = await fetch("match_index.json?v=" + (window.MATCH_V || "1"));
    if (!r.ok) throw new Error("색인을 불러오지 못했어요");
    const d = await r.json();
    d.vid = new Map(d.vocab.map(function (t, i) { return [t, i]; }));
    IDX = d;
    CV = d.c.map(function (c) { return { P: arrMap(c.P), M: arrMap(c.M), S: arrMap(c.S) }; });
  }

  // 문장과 사용자 입력 사이에 겹치는 토큰 수
  function overlap(sentTokens, qset) { let n = 0; const seen = new Set(); sentTokens.forEach(function (t) { if (qset.has(t) && !seen.has(t)) { seen.add(t); n++; } }); return n; }
  function bestSentences(sents, qset, limit) {
    return sents.map(function (s) { return { s: s, n: overlap(tok(s), qset) }; })
      .filter(function (x) { return x.n >= 2; }).sort(function (a, b) { return b.n - a.n; }).slice(0, limit);
  }
  function userQuote(text, sentence) {
    const st = new Set(tok(sentence));
    let best = null, bn = 1;
    String(text).split(/[\n;·\/]|\.(?:\s|$)|,\s/).forEach(function (seg) {
      seg = seg.trim(); if (seg.length < 3) return;
      const n = overlap(tok(seg), st); if (n > bn) { bn = n; best = seg; }
    });
    return best;
  }
  function words(text) { const w = (String(text).match(/[가-힣A-Za-z0-9&]{2,}/g) || []); return Array.from(new Set(w)).sort(function (a, b) { return b.length - a.length; }); }
  function esc(s) { return String(s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function hi(sentence, userText) {
    let h = esc(sentence);
    const ws = words(userText).filter(function (w) { return h.indexOf(w) >= 0; }).slice(0, 12);
    if (!ws.length) return h;
    const re = new RegExp("(" + ws.map(function (w) { return w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); }).join("|") + ")", "g");
    return h.replace(re, "<mark>$1</mark>");
  }

  // 입력 → 후보 목록
  function run(inp) {
    const qP = qvec(inp.products), qM = qvec(inp.materials), qC = qvec(inp.customers), qT = qvec(inp.tech + "\n" + inp.issues);
    const qsetP = new Set(tok(inp.products)), qsetM = new Set(tok(inp.materials)), qsetC = new Set(tok(inp.customers)), qsetT = new Set(tok(inp.tech + "\n" + inp.issues));
    const ex = inp.exclude.split(/[,\n]/).map(function (s) { return s.trim(); }).filter(Boolean);
    const out = [];
    IDX.c.forEach(function (c, k) {
      if (ex.some(function (e) { return c.n.indexOf(e) >= 0; })) return;
      const v = CV[k];
      const s = { h: dot(qP, v.P), vb: dot(qP, v.M), vf: dot(qM, v.P), cu: dot(qC, v.S) + 0.5 * dot(qC, v.P), cap: dot(qT, v.P) };
      const score = WEIGHT.h * s.h + WEIGHT.v * Math.max(s.vb, s.vf) + WEIGHT.cu * s.cu + WEIGHT.cap * s.cap;
      if (score < 0.04) return;
      out.push({ k: k, c: c, s: s, score: score });
    });
    out.sort(function (a, b) { return b.score - a.score; });
    let res = [];
    for (let i = 0; i < out.length && res.length < 40; i++) {
      const o = out[i], c = o.c, reasons = [];
      const spec = [
        ["h", inp.products, qsetP, c.e.P], ["vb", inp.products, qsetP, c.e.M], ["vf", inp.materials, qsetM, c.e.P],
        ["cu", inp.customers, qsetC, (c.e.S || []).concat(c.e.P || [])], ["cap", inp.tech + "\n" + inp.issues, qsetT, c.e.P]
      ];
      spec.forEach(function (sp) {
        const t = sp[0]; if (o.s[t] < MIN[t]) return;
        const ev = bestSentences(sp[3] || [], sp[2], 2);
        if (!ev.length) return;                       // 근거 문장이 없으면 그 유형은 이유로 쓰지 않는다
        reasons.push({ t: t, ev: ev.map(function (e) { return { co: hi(e.s, sp[1]), me: userQuote(sp[1], e.s) }; }), val: o.s[t] });
      });
      if (!reasons.length) continue;                  // 근거가 하나도 없으면 후보에서 제외
      reasons.sort(function (a, b) { return b.val - a.val; });
      res.push({ c: c, score: o.score, reasons: reasons });
    }
    if (res.length) {
      const top = res[0].score;
      res = res.filter(function (r) { return r.score / top >= 0.3; });   // 너무 약한 일치는 숨긴다
      res.forEach(function (r) { const x = r.score / top; r.grade = x >= 0.65 && r.reasons[0].val >= 0.2 ? "상" : (x >= 0.4 ? "중" : "하"); });
    }
    return res;
  }

  // 확인 필요 박스 (후보 선정에는 쓰지 않고 참고·경고로만 표시)
  function checks(c, inp) {
    const f = c.f, out = [];
    const rev = f[0], op = f[1], eq = f[2], debt = f[3];
    if (op !== null && op < 0) out.push(["warn", "2025 영업적자 (" + op.toLocaleString() + "억원)"]);
    if (eq !== null && eq <= 0) out.push(["warn", "자본총계 0 이하 — 자본잠식 가능성"]);
    else if (eq && debt && debt / eq > 3) out.push(["warn", "부채비율 " + Math.round(debt / eq * 100) + "% — 재무 부담 확인"]);
    if (/홀딩스|지주|Holdings|HOLDINGS/.test(c.n)) out.push(["info", "지주사 — 실제 사업은 자회사에서 할 수 있어요. 자회사·계열사 사업을 확인하세요"]);
    out.push(["info", "최대주주·계열·같은 사업의 계열사 보유 여부는 DART 공시로 확인이 필요해요"]);
    if (inp.rev && rev) { const r = rev / inp.rev; if (r > 50) out.push(["info", "매도 기업 매출의 약 " + Math.round(r) + "배 규모 — 소규모 딜에 관심이 낮을 수 있어요"]); else if (r < 1) out.push(["warn", "매도 기업보다 매출이 작아요 — 인수 여력 확인"]); }
    if (c.m === "코넥스") out.push(["info", "코넥스 상장사"]);
    if (c.a[0] > 0) out.push(["ok", "최근 5년 타법인 인수 공시 " + c.a[0] + "건 (최근 " + c.a[1].replace(/(\d{4})(\d\d)(\d\d)/, "$1-$2-$3") + ")"]);
    else out.push(["info", "최근 5년 타법인 인수 공시 없음"]);
    return out;
  }
  function won(v) { return v === null || v === undefined ? "-" : v.toLocaleString(undefined, { maximumFractionDigits: 1 }); }

  window.MNA_MATCH = { load: load, run: run, checks: checks, TYPES: TYPES, esc: esc, won: won, count: function () { return IDX ? IDX.c.length : 0; }, built: function () { return IDX ? IDX.built : ""; } };
})();
