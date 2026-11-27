/* 피어그룹 가치평가: ① 피어그룹 배수법(TTM, 6개월 평균 시가총액, 비상장 할인) ② 간이 DCF ③ 종합
 * 계산 구조는 실무 양식과 같다.
 *   피어 EV = 시가총액(6개월 평균 종가 × 자기주식 제외 주식수) + 차입금 − (현금 + 단기금융상품)
 *   피어 EV/EBITDA = EV ÷ TTM EBITDA,  PER = 시가총액 ÷ TTM 지배주주 순이익
 *   대상 EV = 가중평균 EBITDA × 평균 EV/EBITDA × (1 − 비상장 할인율),  지분가치 = EV + 순현금
 *   대상 지분가치(PER) = 가중평균 순이익 × 평균 PER × (1 − 할인율),  EV(PER) = 지분가치 − 순현금
 * 입력값은 이 브라우저의 sessionStorage 에만 저장되고 서버로 전송되지 않는다.
 * 금액 단위: 화면 입력·표시는 억원, 피어 데이터는 백만원.
 */
(function () {
  var app = document.getElementById("app");
  var SS = "mnaPeerValV1";
  var U = null, UIDX = {}, SECT = null, tab = "peer", q = "";
  var S = load() || defaults();

  renderSidebar("sell");

  function defaults() {
    var y = new Date().getFullYear() - 1;
    return {
      name: "", baseDate: new Date(Date.now() + 9 * 3600e3).toISOString().slice(0, 10),
      years: [y - 2, y - 1, y], op: ["", "", ""], da: ["", "", ""], ni: ["", "", ""], w: [20, 30, 50],
      cash: "", stf: "", debt: "", effTax: "", normTax: 20,
      peers: [], off: {}, lease: false, stat: "avg", disc: "30, 50",
      dcf: { rev: "", growth: "10, 8, 6, 5, 4", margin: "", da: "", capex: "", dso: 60, dio: 45, dpo: 45, tax: 20,
             rf: 3.0, beta: 1.0, mrp: 6.0, size: 3.0, spec: 2.0, g: 1.0, exit: "", wG: 50, disc: 30 }
    };
  }
  function save() { try { sessionStorage.setItem(SS, JSON.stringify(S)); } catch (e) {} }
  function load() { try { var s = JSON.parse(sessionStorage.getItem(SS) || "null"); if (s && s.years) { var d = defaults(); s.dcf = Object.assign(d.dcf, s.dcf || {}); return Object.assign(d, s); } } catch (e) {} return null; }

  // ── 유틸 ──
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function n(v) { if (v === "" || v == null) return NaN; var x = Number(String(v).replace(/[,\s]/g, "")); return isFinite(x) ? x : NaN; }
  function z(v) { var x = n(v); return isFinite(x) ? x : 0; }
  function eok(v, d) { if (!isFinite(v)) return "-"; d = d == null ? 1 : d; return v.toLocaleString("ko-KR", { minimumFractionDigits: d, maximumFractionDigits: d }); }
  function mx(v) { return isFinite(v) ? v.toFixed(2) + "x" : "-"; }
  function pc(v, d) { return isFinite(v) ? (v * 100).toFixed(d == null ? 1 : d) + "%" : "-"; }
  function list(s) { return String(s || "").split(/[,\s]+/).map(n).filter(isFinite); }
  function avg(a) { return a.length ? a.reduce(function (s, x) { return s + x; }, 0) / a.length : NaN; }
  function med(a) { if (!a.length) return NaN; var b = a.slice().sort(function (x, y) { return x - y; }), m = b.length >> 1; return b.length % 2 ? b[m] : (b[m - 1] + b[m]) / 2; }
  function ymd(s) { return s ? s.slice(0, 4) + "." + s.slice(4, 6) + "." + s.slice(6, 8) : ""; }

  // ── 데이터 ──
  Promise.all([
    fetch("peer_universe.json?t=" + Date.now()).then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; }),
    fetch("peers.json").then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; })
  ]).then(function (res) {
    U = res[0]; SECT = res[1];
    if (U && U.c) U.c.forEach(function (e) { UIDX[e.c] = e; });
    render();
  });

  // 피어 한 곳의 배수 계산 (백만원)
  function peerCalc(code) {
    var e = UIDX[code];
    if (!e) return null;
    var t = e.t || [], b = e.b || [], s = e.s, px = e.px;
    var r = { code: code, name: e.n, mkt: e.m, per: e.per, note: e.note, fs: e.fs === "CFS" ? "연결" : "별도", own: e.own, flags: [] };
    r.rev = t[0]; r.op = t[1]; r.da = t[2]; r.ni = t[3];
    r.ebitda = r.op == null ? NaN : r.op + (r.da || 0);
    if (r.da == null) r.flags.push("상각비 없음(영업이익만)");
    r.cash = (b[0] || 0) + (b[1] || 0); r.debt = (b[2] || 0) + (S.lease ? (b[3] || 0) : 0); r.lease = b[3] || 0;
    r.shares = s ? s[2] : NaN; r.tre = s ? s[1] : 0;
    r.px = px ? px.avg : NaN; r.pxN = px ? px.n : 0; r.pxFrom = px ? px.from : ""; r.pxTo = px ? px.to : "";
    r.mcap = r.px * r.shares / 1e6;
    r.ev = r.mcap + r.debt - r.cash;
    r.evEbitda = r.ebitda > 0 ? r.ev / r.ebitda : NaN;
    r.perX = r.ni > 0 ? r.mcap / r.ni : NaN;
    if (!(r.ebitda > 0)) r.flags.push("EBITDA 적자 → EV/EBITDA 제외");
    if (!(r.ni > 0)) r.flags.push("순손실 → PER 제외");
    if (r.evEbitda > 40) r.flags.push("EV/EBITDA 40배 초과(이상치 확인)");
    if (r.perX > 60) r.flags.push("PER 60배 초과(이상치 확인)");
    if (!e.own) r.flags.push("지배주주 순이익 미표시 → 당기순이익 사용");
    if (!s) r.flags.push("주식수 없음");
    return r;
  }

  function peerStats() {
    var rows = S.peers.map(peerCalc).filter(Boolean);
    var on = rows.filter(function (r) { return !S.off[r.code]; });
    var ev = on.map(function (r) { return r.evEbitda; }).filter(isFinite);
    var pe = on.map(function (r) { return r.perX; }).filter(isFinite);
    var f = S.stat === "med" ? med : avg;
    return { rows: rows, evEbitda: f(ev), per: f(pe), nEv: ev.length, nPe: pe.length };
  }

  // 대상회사 가중 지표 (억원)
  function target() {
    var eb = [], ni = [], w = S.w.map(z), ws = w.reduce(function (s, x) { return s + x; }, 0) || 1;
    for (var i = 0; i < 3; i++) { eb.push(z(S.op[i]) + z(S.da[i])); ni.push(z(S.ni[i])); }
    var wEb = 0, wNi = 0;
    for (i = 0; i < 3; i++) { wEb += eb[i] * w[i] / ws; wNi += ni[i] * w[i] / ws; }
    var net = z(S.cash) + z(S.stf) - z(S.debt);
    var eff = n(S.effTax) / 100, nt = n(S.normTax) / 100;
    var wNiNorm = isFinite(eff) && eff < 1 && isFinite(nt) ? wNi / (1 - eff) * (1 - nt) : NaN;
    return { eb: eb, ni: ni, w: w, ws: ws, wEb: wEb, wNi: wNi, net: net, wNiNorm: wNiNorm, filled: S.op.concat(S.ni).some(function (v) { return v !== ""; }) };
  }

  function valuation() {
    var P = peerStats(), T = target();
    var ds = list(S.disc).map(function (x) { return x / 100; }).filter(function (x) { return x >= 0 && x < 1; });
    if (ds.indexOf(0) < 0) ds.push(0);
    var cols = ds.map(function (d) {
      var mEv = P.evEbitda * (1 - d), mPe = P.per * (1 - d);
      var ev1 = T.wEb * mEv, eq1 = ev1 + T.net, eq2 = T.wNi * mPe, ev2 = eq2 - T.net;
      var eqN = T.wNiNorm * mPe;
      var eqs = [eq1, eq2].filter(isFinite), evs = [ev1, ev2].filter(isFinite);
      return { d: d, mEv: mEv, mPe: mPe, ev1: ev1, eq1: eq1, eq2: eq2, ev2: ev2, eqAvg: avg(eqs), evAvg: avg(evs), eqN: eqN, evN: eqN - T.net };
    });
    return { P: P, T: T, cols: cols };
  }

  // ── 렌더 ──
  function render() {
    var dataNote = U ? "상장사 " + U.n.toLocaleString() + "곳 · 기준 " + esc(U.updated) + (U.pending ? " · 갱신 대기 " + U.pending + "곳" : "") : "상장사 데이터를 준비 중이에요(하루 이틀 안에 채워져요)";
    app.innerHTML =
      '<div class="pv-head"><h1>피어그룹 가치평가</h1>' +
      '<p>대상회사 재무를 넣고 비교 상장사를 고르면 <b>피어그룹 배수법</b>(EV/EBITDA·PER, 비상장 할인)과 <b>DCF</b>로 가치를 계산해요. 공개자료 기반 · ' + dataNote + '</p>' +
      '<div class="privacy">🔒 입력한 재무는 이 브라우저 안에서만 계산돼요. 서버로 전송되지 않고, 탭을 닫으면 사라져요.</div></div>' +
      '<div class="pv-tabs">' + [["peer", "① 피어그룹 배수법"], ["dcf", "② DCF"], ["sum", "③ 종합"]].map(function (t) {
        return '<button data-tab="' + t[0] + '" class="' + (tab === t[0] ? "on" : "") + '">' + t[1] + '</button>'; }).join("") + '</div>' +
      '<div id="pane"></div>';
    app.querySelectorAll("[data-tab]").forEach(function (b) { b.onclick = function () { tab = b.dataset.tab; render(); }; });
    if (tab === "peer") renderPeer(); else if (tab === "dcf") renderDcf(); else renderSum();
  }

  function inp(key, val, ph, cls) { return '<input class="pv-in ' + (cls || "") + '" data-k="' + key + '" value="' + esc(val) + '" placeholder="' + esc(ph || "") + '" inputmode="decimal">'; }

  function targetHtml() {
    var T = target();
    var h = '<section class="pv-card"><h2>1. 대상회사 재무 <span class="unit">(억원)</span></h2>' +
      '<div class="pv-row"><label>회사명(선택)</label><input class="pv-in wide" data-k="name" value="' + esc(S.name) + '" placeholder="예: ○○종묘"></div>' +
      '<div class="tscroll"><table class="pv-t in"><thead><tr><th></th>' + S.years.map(function (y, i) { return '<th>' + inp("years." + i, y, "", "yr") + '</th>'; }).join("") + '</tr></thead><tbody>' +
      row3("영업이익", "op") + row3("감가상각비+무형자산상각비", "da") +
      '<tr class="calc"><td>EBITDA (자동)</td>' + T.eb.map(function (v) { return '<td>' + eok(v, 2) + '</td>'; }).join("") + '</tr>' +
      row3("당기순이익", "ni") + row3("가중치(%)", "w") +
      '</tbody></table></div>' +
      '<div class="pv-grid">' +
        '<div class="pv-row"><label>현금및현금성자산</label>' + inp("cash", S.cash, "0") + '</div>' +
        '<div class="pv-row"><label>단기금융상품·단기예금</label>' + inp("stf", S.stf, "0") + '</div>' +
        '<div class="pv-row"><label>차입금 총계(단기·장기·사채)</label>' + inp("debt", S.debt, "0") + '</div>' +
        '<div class="pv-row"><label>순현금 (자동)</label><div class="pv-val">' + eok(T.net, 2) + '</div></div>' +
        '<div class="pv-row"><label>실효세율(%) <i>선택</i></label>' + inp("effTax", S.effTax, "예: 1.6") + '</div>' +
        '<div class="pv-row"><label>정상화 세율(%)</label>' + inp("normTax", S.normTax, "20") + '</div>' +
      '</div>' +
      '<p class="hint">실효세율을 넣으면 감면 전 세율(정상화 세율)로 바꾼 순이익 기준 PER 결과를 참고로 함께 보여줘요. 예: 농업회사법인처럼 세금 감면이 큰 회사.</p></section>';
    return h;
    function row3(lab, k) { return '<tr><td>' + lab + '</td>' + [0, 1, 2].map(function (i) { return '<td>' + inp(k + "." + i, S[k][i], "") + '</td>'; }).join("") + '</tr>'; }
  }

  function peerPickHtml() {
    var h = '<section class="pv-card"><h2>2. 비교 상장사(Peer Group)</h2>';
    if (!U) h += '<div class="warn">상장사 데이터가 아직 준비되지 않았어요. 하루 이틀 뒤 다시 열어 주세요.</div>';
    h += '<div class="pv-pick"><input class="pv-in wide" id="pq" placeholder="회사명 또는 종목코드로 추가 (예: 농우, 054050)" value="' + esc(q) + '" autocomplete="off"><div id="pqList" class="pq-list"></div></div>';
    if (SECT && SECT.sectors) {
      h += '<div class="pv-sect"><span>업종 대표 상장사 한 번에 추가:</span> <select id="sectSel"><option value="">업종 선택</option>' +
        SECT.sectors.map(function (s) { return '<option value="' + esc(s.id) + '">' + esc(s.name) + '</option>'; }).join("") + '</select></div>';
    }
    h += '<div class="pv-opts"><label><input type="checkbox" id="optLease"' + (S.lease ? " checked" : "") + '> 리스부채를 차입금에 포함</label>' +
      '<label>평균 방식 <select id="optStat"><option value="avg"' + (S.stat === "avg" ? " selected" : "") + '>단순평균</option><option value="med"' + (S.stat === "med" ? " selected" : "") + '>중앙값</option></select></label></div>';
    var P = peerStats();
    if (!P.rows.length) return h + '<p class="hint">비교할 상장사를 추가해 주세요. 사업 구조·판매채널이 비슷한 2~6곳이 적당해요.</p></section>';
    h += '<div class="tscroll"><table class="pv-t peers"><thead><tr><th>포함</th><th>회사</th><th>기준</th><th>6개월<br>평균주가</th><th>주식수<br>(자사주 제외)</th><th>시가총액</th><th>차입금</th><th>현금</th><th>EV</th><th>TTM<br>EBITDA</th><th>TTM<br>지배순이익</th><th>EV/EBITDA</th><th>PER</th><th></th></tr></thead><tbody>';
    P.rows.forEach(function (r) {
      var off = !!S.off[r.code];
      h += '<tr class="' + (off ? "off" : "") + '"><td><input type="checkbox" data-on="' + r.code + '"' + (off ? "" : " checked") + '></td>' +
        '<td><b>' + esc(r.name) + '</b><span class="sm">' + esc(r.code) + ' · ' + esc(r.mkt || "") + ' · ' + r.fs + '</span>' + (r.flags.length ? '<span class="flag">' + r.flags.map(esc).join(" · ") + '</span>' : '') + '</td>' +
        '<td class="sm2" title="' + esc(r.note || "") + '">' + esc((r.per || "").replace(/^20/, "")) + ' TTM</td>' +
        '<td>' + (isFinite(r.px) ? Math.round(r.px).toLocaleString() + '원<span class="sm">' + r.pxN + '거래일</span>' : '-') + '</td>' +
        '<td>' + (isFinite(r.shares) ? r.shares.toLocaleString() : '-') + '</td>' +
        '<td>' + eok(r.mcap / 100) + '</td><td>' + eok(r.debt / 100) + '</td><td>' + eok(r.cash / 100) + '</td><td>' + eok(r.ev / 100) + '</td>' +
        '<td>' + eok(r.ebitda / 100) + '</td><td>' + eok(r.ni / 100) + '</td>' +
        '<td class="mx">' + mx(r.evEbitda) + '</td><td class="mx">' + mx(r.perX) + '</td>' +
        '<td><button class="x" data-del="' + r.code + '" title="삭제">✕</button></td></tr>';
    });
    h += '<tr class="calc"><td></td><td colspan="10">' + (S.stat === "med" ? "중앙값" : "단순평균") + ' (포함 체크된 회사, 적자 제외)</td><td class="mx">' + mx(P.evEbitda) + '<span class="sm">' + P.nEv + '곳</span></td><td class="mx">' + mx(P.per) + '<span class="sm">' + P.nPe + '곳</span></td><td></td></tr>';
    h += '</tbody></table></div><p class="hint">금액 억원. 시가총액 = 최근 6개월(직전 거래일까지) 평균 종가 × 자기주식 제외 보통주 수. EV = 시가총액 + 차입금 − 현금·단기금융상품. TTM = 최근 사업보고서 + 최근 분기·반기 누적 − 전년 같은 기간 누적.</p></section>';
    return h;
  }

  function resultHtml() {
    var V = valuation(), T = V.T, P = V.P;
    if (!T.filled || !P.rows.length) return '<section class="pv-card"><h2>3. 평가 결과</h2><p class="hint">대상회사 재무와 비교 상장사를 넣으면 결과가 나와요.</p></section>';
    var c = V.cols;
    function r(lab, f, cls) { return '<tr class="' + (cls || "") + '"><td>' + lab + '</td>' + c.map(function (x) { return '<td>' + f(x) + '</td>'; }).join("") + '</tr>'; }
    var h = '<section class="pv-card"><h2>3. 평가 결과 <span class="unit">(억원)</span></h2>' +
      '<div class="pv-row narrow"><label>비상장 할인율(%) — 쉼표로 여러 개</label>' + inp("disc", S.disc, "30, 50") + '</div>' +
      '<div class="tscroll"><table class="pv-t res"><thead><tr><th></th>' + c.map(function (x) { return '<th>' + (x.d ? "할인 " + Math.round(x.d * 100) + "%" : "할인 전(참고)") + '</th>'; }).join("") + '</tr></thead><tbody>' +
      r("가중평균 EBITDA", function () { return eok(T.wEb, 2); }) +
      r("가중평균 당기순이익", function () { return eok(T.wNi, 2); }) +
      r("순현금", function () { return eok(T.net, 2); }) +
      r("적용 EV/EBITDA", function (x) { return mx(x.mEv); }) +
      r("적용 PER", function (x) { return mx(x.mPe); }) +
      r("EV (EV/EBITDA 기준)", function (x) { return eok(x.ev1); }, "b") +
      r("지분가치 (EV/EBITDA 기준) = EV + 순현금", function (x) { return eok(x.eq1); }) +
      r("지분가치 (PER 기준)", function (x) { return eok(x.eq2); }) +
      r("EV (PER 기준) = 지분가치 − 순현금", function (x) { return eok(x.ev2); }) +
      r("평균 지분가치", function (x) { return eok(x.eqAvg); }, "hl") +
      r("평균 EV", function (x) { return eok(x.evAvg); }, "hl") +
      (isFinite(T.wNiNorm) ? r("(참고) 지분가치 PER 기준, 정상화 순이익 " + eok(T.wNiNorm, 2), function (x) { return eok(x.eqN); }, "ref") : "") +
      '</tbody></table></div>' +
      '<p class="hint">비상장 할인은 배수 × (1 − 할인율)로 적용해요. 피어 배수는 ' + (S.stat === "med" ? "중앙값" : "단순평균") + '이에요.</p>' +
      '<div class="pv-actions"><button class="btn primary" id="xls">엑셀로 내려받기</button><button class="btn" id="reset">입력 초기화</button></div></section>';
    return h;
  }

  function renderPeer() {
    var pane = document.getElementById("pane");
    pane.innerHTML = targetHtml() + peerPickHtml() + resultHtml();
    bindInputs(pane);
    var pq = document.getElementById("pq");
    if (pq) { pq.oninput = function () { q = pq.value; suggest(); }; suggest(); }
    var ss = document.getElementById("sectSel");
    if (ss) ss.onchange = function () {
      var s = SECT.sectors.filter(function (x) { return x.id === ss.value; })[0];
      if (!s) return;
      (s.peers || []).forEach(function (p) { if (p.code && UIDX[p.code] && S.peers.indexOf(p.code) < 0) S.peers.push(p.code); });
      save(); renderPeer();
    };
    var ol = document.getElementById("optLease"); if (ol) ol.onchange = function () { S.lease = ol.checked; save(); renderPeer(); };
    var os = document.getElementById("optStat"); if (os) os.onchange = function () { S.stat = os.value; save(); renderPeer(); };
    pane.querySelectorAll("[data-on]").forEach(function (b) { b.onchange = function () { if (b.checked) delete S.off[b.dataset.on]; else S.off[b.dataset.on] = 1; save(); renderPeer(); }; });
    pane.querySelectorAll("[data-del]").forEach(function (b) { b.onclick = function () { S.peers = S.peers.filter(function (c) { return c !== b.dataset.del; }); delete S.off[b.dataset.del]; save(); renderPeer(); }; });
    var x = document.getElementById("xls"); if (x) x.onclick = exportXlsx;
    var rs = document.getElementById("reset"); if (rs) rs.onclick = function () { S = defaults(); save(); renderPeer(); };
  }

  function suggest() {
    var box = document.getElementById("pqList");
    if (!box) return;
    var s = q.trim();
    if (!s || !U) { box.innerHTML = ""; return; }
    var low = s.toLowerCase();
    var hit = U.c.filter(function (e) { return e.c.indexOf(s) === 0 || (e.n || "").toLowerCase().indexOf(low) >= 0; }).slice(0, 8);
    box.innerHTML = hit.map(function (e) {
      return '<button data-add="' + e.c + '">' + esc(e.n) + ' <span>' + e.c + ' · ' + esc(e.m || "") + ' · ' + esc(e.per || "") + '</span></button>'; }).join("") || '<div class="none">찾는 회사가 없어요</div>';
    box.querySelectorAll("[data-add]").forEach(function (b) { b.onclick = function () { if (S.peers.indexOf(b.dataset.add) < 0) S.peers.push(b.dataset.add); q = ""; save(); renderPeer(); }; });
  }

  // 입력칸: 값 저장 후 계산 영역만 갱신 (포커스 유지)
  function bindInputs(root) {
    root.querySelectorAll("[data-k]").forEach(function (el) {
      el.addEventListener("change", function () { setK(el.dataset.k, el.value); save(); if (tab === "peer") renderPeer(); else if (tab === "dcf") renderDcf(); });
    });
  }
  function setK(k, v) {
    var p = k.split("."), o = S;
    for (var i = 0; i < p.length - 1; i++) o = o[p[i]];
    o[p[p.length - 1]] = v;
  }

  // ── DCF ──
  function dcfModel(ov) {
    var D = S.dcf, T = target();
    var rev0 = n(D.rev);
    var gr = list(D.growth).map(function (x) { return x / 100; });
    while (gr.length < 5) gr.push(gr.length ? gr[gr.length - 1] : 0);
    var mg = list(D.margin).map(function (x) { return x / 100; });
    if (!mg.length) { var lastEb = T.eb[2]; mg = [rev0 > 0 && isFinite(lastEb) ? lastEb / rev0 : 0.1]; }
    while (mg.length < 5) mg.push(mg[mg.length - 1]);
    var rev = [], r = rev0;
    for (var i = 0; i < 5; i++) { r = r * (1 + gr[i]); rev.push(r * 100); } // 억 → 백만
    var w = DCF.buildWacc({ rf: z(D.rf) / 100, beta: z(D.beta), mrp: z(D.mrp) / 100, size: z(D.size) / 100, specific: z(D.spec) / 100, debtWeight: 0 });
    var P = peerStats();
    var exit = isFinite(n(D.exit)) ? n(D.exit) : (isFinite(P.evEbitda) ? P.evEbitda * (1 - z(D.disc) / 100) : 6);
    var daV = isFinite(n(D.da)) ? n(D.da) * 100 : z(S.da[2]) * 100;
    var capex = isFinite(n(D.capex)) ? n(D.capex) * 100 : daV;
    var cash0 = rev0 * 100 * (1 - mg[0]);
    var common = {
      stub: 1, taxRate: z(D.tax) / 100, mid: 1, termCapexRatio: 1,
      actual: { ebitda: T.eb[2] * 100, ar: rev0 * 100 * z(D.dso) / 365, inv: cash0 * z(D.dio) / 365, ap: cash0 * z(D.dpo) / 365 },
      uncertainLast: 0, uncertainFwd: 0,
      bridge: { cash: (z(S.cash) + z(S.stf)) * 100, finAssets: 0, debt: z(S.debt) * 100, retire: 0, taxPayable: 0, minCash: 0, nonOpInclude: 0, nonOpAssets: 0, nonOpLiabs: 0, nonOpTax: 0 }
    };
    var scen = { rev: rev, margin: mg.slice(0, 5), addbackFixed: 0, uncertainRatio: 0, da: daV, capex: capex,
                 dso: z(D.dso), dio: z(D.dio), dpo: z(D.dpo), wacc: w.applied, g: z(D.g) / 100, exit: exit, wGordon: z(D.wG) / 100 };
    return { common: common, scen: scen, wacc: w, exit: exit, ok: rev0 > 0 };
  }

  function renderDcf() {
    var D = S.dcf, M = dcfModel();
    function f(label, key, ph, unit, hint) { return '<div class="pv-row"><label>' + label + (hint ? ' <i>' + hint + '</i>' : '') + '</label><div class="pv-u">' + inp("dcf." + key, D[key], ph) + '<span>' + (unit || "") + '</span></div></div>'; }
    var h = '<section class="pv-card"><h2>DCF 가정</h2><p class="hint">피어그룹 탭의 최근연도 EBITDA·상각비·순현금을 기본값으로 써요. 1년차는 다음 회계연도, 현금흐름은 연중 발생(mid-year)으로 할인해요.</p><div class="pv-grid">' +
      f("기준연도 매출액", "rev", "예: 50", "억원") +
      f("5개년 매출 성장률", "growth", "10, 8, 6, 5, 4", "%", "쉼표로 연도별") +
      f("EBITDA 마진", "margin", "비우면 최근연도 마진", "%", "하나 또는 5개") +
      f("감가상각비(연)", "da", "비우면 최근연도", "억원") +
      f("CAPEX(연)", "capex", "비우면 상각비와 동일", "억원") +
      f("매출채권 회전일수", "dso", "60", "일") + f("재고자산 회전일수", "dio", "45", "일") + f("매입채무 회전일수", "dpo", "45", "일") +
      f("법인세율", "tax", "20", "%") +
      '</div><h3>할인율 (자기자본비용 build-up)</h3><div class="pv-grid">' +
      f("무위험이자율", "rf", "3.0", "%") + f("베타", "beta", "1.0", "") + f("시장위험프리미엄", "mrp", "6.0", "%") +
      f("규모 프리미엄", "size", "3.0", "%") + f("기업 고유위험", "spec", "2.0", "%") +
      '<div class="pv-row"><label>할인율(WACC, 무차입 가정)</label><div class="pv-val">' + pc(M.wacc.applied) + '</div></div>' +
      '</div><h3>잔존가치</h3><div class="pv-grid">' +
      f("영구성장률", "g", "1.0", "%") +
      f("Exit EV/EBITDA", "exit", isFinite(peerStats().evEbitda) ? "비우면 피어 평균 × (1−할인)" : "6", "배") +
      f("Exit 배수에 쓰는 할인율", "disc", "30", "%") +
      f("영구성장법 가중치", "wG", "50", "%", "나머지는 Exit 배수법") +
      '</div></section>';
    if (!M.ok) { h += '<section class="pv-card"><p class="hint">기준연도 매출액을 넣으면 결과가 나와요.</p></section>'; }
    else {
      var R = DCF.runScenario(M.common, M.scen);
      var y0 = Number(S.years[2]) || new Date().getFullYear() - 1;
      h += '<section class="pv-card"><h2>DCF 결과 <span class="unit">(억원)</span></h2><div class="pv-kpi">' +
        kpi("EV (가중)", R.ev / 100) + kpi("지분가치", R.equity / 100) + kpi("영구성장법 EV", R.evGordon / 100) + kpi("Exit 배수법 EV", R.evExit / 100) + '</div>' +
        '<p class="hint">적용 Exit 배수 ' + mx(M.exit) + ' · 영구성장법이 내포한 배수 ' + mx(R.impliedMultipleGordon) + ' · 잔존가치 비중 ' + pc(R.tvShare) + '</p>' +
        '<div class="tscroll"><table class="pv-t"><thead><tr><th></th>' + R.rows.map(function (_, i) { return '<th>' + (y0 + i + 1) + 'E</th>'; }).join("") + '</tr></thead><tbody>' +
        line("매출액", "rev") + line("EBITDA", "normEbitda") + line("세후영업이익", "nopat") + line("CAPEX", "capex") + line("운전자본 증감", "dNwc") + line("FCF", "fcf") + line("현재가치", "pv") +
        '</tbody></table></div>' + sens(M) + '</section>';
      function line(l, k) { return '<tr><td>' + l + '</td>' + R.rows.map(function (r) { return '<td>' + eok(r[k] / 100) + '</td>'; }).join("") + '</tr>'; }
    }
    h += '<p class="hint">정상화(대표 급여·개인 비용 조정), 비영업자산, 퇴직급여 등을 반영한 자세한 DCF는 <a href="valuation.html">매도 가격 확인해보기 설문</a>에서 할 수 있어요.</p>';
    var pane = document.getElementById("pane");
    pane.innerHTML = h;
    bindInputs(pane);
  }
  function kpi(l, v) { return '<div><span>' + l + '</span><b>' + eok(v) + '</b></div>'; }
  function sens(M) {
    var w = [-0.02, -0.01, 0, 0.01, 0.02].map(function (d) { return M.scen.wacc + d; });
    var g = [-0.01, -0.005, 0, 0.005, 0.01].map(function (d) { return M.scen.g + d; });
    var grid = DCF.sensitivity(M.common, M.scen, "wacc", w, "g", g, "equity");
    return '<h3>지분가치 민감도 (WACC × 영구성장률)</h3><div class="tscroll"><table class="pv-t sens"><thead><tr><th>WACC \\ g</th>' + g.map(function (x) { return '<th>' + pc(x) + '</th>'; }).join("") + '</tr></thead><tbody>' +
      grid.map(function (rw, i) { return '<tr><th>' + pc(w[i]) + '</th>' + rw.map(function (v, j) { return '<td class="' + (i === 2 && j === 2 ? "hl" : "") + '">' + eok(v / 100) + '</td>'; }).join("") + '</tr>'; }).join("") + '</tbody></table></div>';
  }

  // ── 종합 ──
  function dcfRange() {
    var M = dcfModel();
    if (!M.ok) return null;
    var lo = DCF.runScenario(M.common, M.scen, { wacc: M.scen.wacc + 0.01 }).equity / 100;
    var mid = DCF.runScenario(M.common, M.scen).equity / 100;
    var hi = DCF.runScenario(M.common, M.scen, { wacc: M.scen.wacc - 0.01 }).equity / 100;
    return [lo, mid, hi];
  }
  function renderSum() {
    var V = valuation(), rows = [];
    var c = V.cols.filter(function (x) { return x.d > 0; }).sort(function (a, b) { return b.d - a.d; });
    if (V.T.filled && V.P.rows.length && c.length) {
      var hiD = c[c.length - 1], loD = c[0];
      if (isFinite(hiD.eq1)) rows.push(["EV/EBITDA 배수법", "할인 " + Math.round(loD.d * 100) + "% ~ " + Math.round(hiD.d * 100) + "%", loD.eq1, (loD.eq1 + hiD.eq1) / 2, hiD.eq1]);
      if (isFinite(hiD.eq2)) rows.push(["PER 배수법", "할인 " + Math.round(loD.d * 100) + "% ~ " + Math.round(hiD.d * 100) + "%", loD.eq2, (loD.eq2 + hiD.eq2) / 2, hiD.eq2]);
      if (isFinite(hiD.eqN)) rows.push(["PER (정상화 순이익)", "참고", loD.eqN, (loD.eqN + hiD.eqN) / 2, hiD.eqN]);
    }
    var d = dcfRange();
    if (d) rows.push(["DCF", "WACC ±1%p", d[0], d[1], d[2]]);
    var pane = document.getElementById("pane");
    if (!rows.length) { pane.innerHTML = '<section class="pv-card"><p class="hint">피어그룹 배수법이나 DCF 탭에 입력하면 지분가치 범위를 한눈에 비교해 보여줘요.</p></section>'; return; }
    var all = []; rows.forEach(function (r) { all.push(r[2], r[4]); });
    var lo = Math.min.apply(null, all), hi = Math.max.apply(null, all), pad = (hi - lo) * 0.08 || 1; lo -= pad; hi += pad;
    function pos(v) { return Math.max(0, Math.min(100, (v - lo) / (hi - lo) * 100)); }
    var h = '<section class="pv-card"><h2>지분가치 범위 한눈에 보기 <span class="unit">(억원, 100% 지분)</span></h2><div class="ff">';
    rows.forEach(function (r, i) {
      var a = Math.min(r[2], r[4]), b = Math.max(r[2], r[4]);
      h += '<div class="ff-row"><div class="ff-lab"><b>' + esc(r[0]) + '</b><span>' + esc(r[1]) + '</span></div><div class="ff-track"><div class="ff-bar c' + i + '" style="left:' + pos(a) + '%;width:' + Math.max(1, pos(b) - pos(a)) + '%"></div><div class="ff-mid" style="left:' + pos(r[3]) + '%"></div></div>' +
        '<div class="ff-num">' + eok(a) + ' ~ ' + eok(b) + '</div></div>';
    });
    h += '</div><p class="hint">막대는 범위, 세로선은 중간값이에요. 배수법은 할인율이 클수록 낮은 쪽이에요. 간이 평가이므로 실사·거래구조·협상에 따라 실제 가격은 달라질 수 있어요.</p></section>';
    pane.innerHTML = h;
  }

  // ── 엑셀 내보내기 ──
  function exportXlsx() {
    if (!window.XLSX) { alertBox("엑셀 모듈을 불러오는 중이에요. 잠시 후 다시 눌러 주세요."); return; }
    var V = valuation(), T = V.T, P = V.P, wb = XLSX.utils.book_new();
    var sum = [["피어그룹 배수법 가치평가", S.name || ""], ["평가 기준일", S.baseDate], ["단위", "억원"], [],
      ["항목"].concat(V.cols.map(function (c) { return c.d ? "할인 " + Math.round(c.d * 100) + "%" : "할인 전"; })),
      ["가중평균 EBITDA"].concat(V.cols.map(function () { return T.wEb; })),
      ["가중평균 당기순이익"].concat(V.cols.map(function () { return T.wNi; })),
      ["순현금"].concat(V.cols.map(function () { return T.net; })),
      ["적용 EV/EBITDA"].concat(V.cols.map(function (c) { return c.mEv; })),
      ["적용 PER"].concat(V.cols.map(function (c) { return c.mPe; })),
      ["EV (EV/EBITDA 기준)"].concat(V.cols.map(function (c) { return c.ev1; })),
      ["지분가치 (EV/EBITDA 기준)"].concat(V.cols.map(function (c) { return c.eq1; })),
      ["지분가치 (PER 기준)"].concat(V.cols.map(function (c) { return c.eq2; })),
      ["EV (PER 기준)"].concat(V.cols.map(function (c) { return c.ev2; })),
      ["평균 지분가치"].concat(V.cols.map(function (c) { return c.eqAvg; })),
      ["평균 EV"].concat(V.cols.map(function (c) { return c.evAvg; }))];
    if (isFinite(T.wNiNorm)) sum.push(["(참고) 지분가치 PER, 정상화 순이익"].concat(V.cols.map(function (c) { return c.eqN; })));
    sum.push([], ["피어 배수 (" + (S.stat === "med" ? "중앙값" : "단순평균") + ")", "EV/EBITDA", P.evEbitda, "PER", P.per]);
    var tgt = [["항목"].concat(S.years.map(String)), ["영업이익"].concat(S.op.map(z)), ["감가상각비+무형자산상각비"].concat(S.da.map(z)), ["EBITDA"].concat(T.eb), ["당기순이익"].concat(S.ni.map(z)), ["가중치(%)"].concat(S.w.map(z)), [],
      ["현금및현금성자산", z(S.cash)], ["단기금융상품", z(S.stf)], ["차입금", z(S.debt)], ["순현금", T.net], ["실효세율(%)", S.effTax], ["정상화 세율(%)", S.normTax]];
    var pr = [["포함", "회사", "종목코드", "시장", "재무 구분", "TTM 기준", "6개월 평균주가(원)", "거래일 수", "주가 기간", "주식수(자기주식 제외)", "시가총액(억)", "차입금(억)", "현금·단기금융(억)", "EV(억)", "TTM 매출(억)", "TTM 영업이익(억)", "TTM 상각비(억)", "TTM EBITDA(억)", "TTM 지배순이익(억)", "EV/EBITDA", "PER", "비고"]];
    P.rows.forEach(function (r) {
      pr.push([S.off[r.code] ? "제외" : "포함", r.name, r.code, r.mkt, r.fs, r.note, Math.round(r.px), r.pxN, ymd(r.pxFrom) + "~" + ymd(r.pxTo), r.shares, r.mcap / 100, r.debt / 100, r.cash / 100, r.ev / 100,
        r.rev / 100, r.op / 100, (r.da || 0) / 100, r.ebitda / 100, r.ni / 100, r.evEbitda, r.perX, r.flags.join(" / ")]);
    });
    XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet(sum), "Summary");
    XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet(pr), "Peer Group Data");
    XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet(tgt), "대상회사");
    XLSX.writeFile(wb, "PeerGroup_가치평가_" + (S.name || "대상회사") + ".xlsx");
  }
  function alertBox(m) { var d = document.createElement("div"); d.className = "toast"; d.textContent = m; document.body.appendChild(d); setTimeout(function () { d.remove(); }, 2500); }
})();
