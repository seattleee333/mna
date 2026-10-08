/* 매도 가격 확인해보기: 시작 화면 → 안내 → 설문(한 문항씩) → 결과
 * 입력값은 이 브라우저의 sessionStorage(탭을 닫으면 삭제)에만 임시 저장되고 서버로 전송되지 않는다.
 */
(function () {
  var Q = Survey.QUESTIONS, N = Q.length;
  var app = document.getElementById("app");
  var modal = document.getElementById("modal");
  var SS_KEY = "mnaValuationV1";
  var STACK = { ceo: 1, other: 1, capex: 1, cash: 1, liab: 1, nonop: 1, date: 1, family: 1, hope: 1 };

  var A = {}, auto = {}, adv = { g: {}, exit: {} }, step = -1, peers = null, errs = [];

  renderSidebar("sell");

  // ── 유틸 ──
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function res(x) { return Survey.res(x, A); }
  function today() { return new Date(Date.now() + 9 * 3600 * 1000).toISOString().slice(0, 10); }
  function eok(mn, d) { // 백만원 → 억원 문자열
    var v = mn / 100; d = d == null ? 1 : d;
    if (!isFinite(v)) return "-";
    if (Math.abs(v) >= 10000) return (v / 10000).toLocaleString("ko-KR", { maximumFractionDigits: 2 }) + "조";
    return v.toLocaleString("ko-KR", { minimumFractionDigits: d, maximumFractionDigits: d }) + "억";
  }
  function pc(x, d) { return isFinite(x) ? (x * 100).toFixed(d == null ? 1 : d) + "%" : "-"; }
  function mx(x) { return isFinite(x) ? x.toFixed(1) + "x" : "-"; }
  function parseNum(s) {
    s = String(s).replace(/[,\s]/g, "");
    if (s === "" || s === "-") return undefined;
    return /^-?\d*\.?\d*$/.test(s) ? Number(s) : NaN;
  }
  function save() { try { sessionStorage.setItem(SS_KEY, JSON.stringify({ A: A, auto: auto, step: step, adv: adv })); } catch (e) {} }
  function load() {
    try {
      var s = JSON.parse(sessionStorage.getItem(SS_KEY) || "null");
      if (s && s.A) { A = s.A; auto = s.auto || {}; adv = s.adv || { g: {}, exit: {} }; adv.g = adv.g || {}; adv.exit = adv.exit || {}; step = typeof s.step === "number" ? s.step : -1; return true; }
    } catch (e) {}
    return false;
  }
  function clearSave() { try { sessionStorage.removeItem(SS_KEY); } catch (e) {} }
  function top() { window.scrollTo({ top: 0, behavior: "smooth" }); }

  // ── 필요 서류 목록 ──
  var DOCS = [
    ["필수", "최근 3개년 재무제표 (감사보고서 또는 표준재무제표증명) — 매출·영업이익·감가상각비·운전자본·현금·차입금"],
    ["필수", "올해 월별 매출 또는 부가세 신고서, 수주잔고"],
    ["필수", "거래처별 매출 명세 (세금계산서 합계표)"],
    ["필수", "급여대장 또는 임원 보수 내역 (대표·가족)"],
    ["권장", "판매비와관리비 상세 (보험료·차량 등 개인 성격 비용)"],
    ["권장", "올해·내년 사업계획서"],
    ["권장", "은행 잔고증명서, 차입금 명세"],
    ["권장", "퇴직연금·퇴직급여충당부채 내역, 법인세 신고서"],
    ["권장", "비영업 부동산 등기부등본·시세 자료·임대차계약서"]
  ];

  // ── 시작 화면 ──
  function renderIntro() {
    var resume = step >= 0 && Object.keys(A).length > 1;
    app.innerHTML =
      '<div class="val-hero">' +
        '<div class="ico">💰</div>' +
        '<h1>기업마다 매도가격이 달라요</h1>' +
        '<p>기업가치 간이평가를 하려면 설문조사를 완성해주셔야해요.</p>' +
        '<div class="notice-strong">⚠️ <b>간이평가</b>입니다. 입력하신 정보만을 바탕으로 한 단순 추정치이므로 <b>실제 매각가격과 차이가 있을 수 있어요.</b></div>' +
        '<button class="btn primary big" id="goStart">설문조사하고 기업가치 평가해보기</button>' +
        (resume ? '<div class="sub-actions">작성하던 내용이 있어요 · <button id="goResume">이어서 하기</button> · <button id="goReset">처음부터</button></div>' : '') +
      '</div>' +
      '<div class="val-feats">' +
        '<div class="val-feat"><b>DCF 3개 시나리오</b>보수·기본·낙관 세 가지 가정으로 가격 범위를 계산해요.</div>' +
        '<div class="val-feat"><b>업종 피어 배수 비교</b>비슷한 상장사의 EV/EBITDA·PER과 함께 검증해요.</div>' +
        '<div class="val-feat"><b>입력값은 내 브라우저에만</b>서버로 전송되거나 저장되지 않아요.</div>' +
      '</div>';
    document.getElementById("goStart").onclick = openModal;
    var r = document.getElementById("goResume"); if (r) r.onclick = function () { goto(step >= N ? N : step); };
    var z = document.getElementById("goReset"); if (z) z.onclick = function () { resetAll(); renderIntro(); };
  }

  function openModal() {
    var min = Math.round(N * 0.55), max = Math.round(N * 0.75);
    modal.hidden = false;
    modal.innerHTML =
      '<div class="modal" role="dialog" aria-modal="true">' +
        '<h2>시작하기 전에 알려드려요</h2>' +
        '<p class="lead">질문에 하나씩 답하면 DCF(현금흐름할인) 방식으로 예상 매도가격을 계산해 드려요.</p>' +
        '<div class="stat-row">' +
          '<div class="stat"><b>' + N + '개</b><span>총 질문 수</span></div>' +
          '<div class="stat"><b>약 ' + min + '~' + max + '분</b><span>예상 소요 시간</span></div>' +
          '<div class="stat"><b>' + DOCS.filter(function (d) { return d[0] === "필수"; }).length + '종</b><span>필수 자료</span></div>' +
        '</div>' +
        '<div class="doc-title">미리 옆에 두면 훨씬 빨라요</div>' +
        '<ul class="doc-list">' + DOCS.map(function (d) {
          return '<li><span>' + (d[0] === "필수" ? '<span class="req">필수</span>' : '') + esc(d[1]) + '</span></li>';
        }).join("") + '</ul>' +
        '<div class="notice-strong">⚠️ 간이평가이며, 입력하신 내용만으로 계산하기 때문에 <b>실제와 차이가 있을 수 있어요.</b> 실사·거래구조·협상에 따라 크게 달라질 수 있습니다.</div>' +
        '<div class="privacy">🔒 입력하신 내용은 이 브라우저 안에서만 계산돼요. 서버로 전송되지 않고, 탭을 닫으면 사라져요.</div>' +
        '<div class="btns"><button class="btn ghost" id="mClose">나중에 할게요</button><button class="btn primary" id="mStart">시작하기</button></div>' +
      '</div>';
    document.getElementById("mClose").onclick = closeModal;
    document.getElementById("mStart").onclick = function () { closeModal(); resetAll(true); goto(0); };
    modal.onclick = function (e) { if (e.target === modal) closeModal(); };
  }
  function closeModal() { modal.hidden = true; modal.innerHTML = ""; }

  function resetAll(keepDate) {
    A = {}; auto = {}; adv = { g: {}, exit: {} }; step = -1; errs = [];
    A.baseDate = today();
    clearSave();
  }

  function goto(s) {
    step = s; errs = []; save();
    if (step < 0) renderIntro();
    else if (step >= N) renderResult();
    else renderQ();
    top();
  }

  // ── 질문 화면 ──
  function applyDefaults(q) {
    (q.fields || []).forEach(function (f) {
      if (!f.def) return;
      if (A[f.id] === undefined || auto[f.id]) {
        var v = f.def(A);
        auto[f.id] = true; // 사용자가 직접 입력하기 전까지는 다른 입력에 맞춰 제안값을 갱신한다
        if (v !== undefined && isFinite(v) && (v !== 0 || f.id === "nonOpInclude")) A[f.id] = v;
        else delete A[f.id];
      }
    });
  }

  function fieldHtml(f) {
    var id = f.id, lab = esc(res(f.label)), v = A[id];
    var cls = "field" + (f.chip ? " " + f.chip : "") + (auto[id] && v !== undefined && f.type !== "toggle" ? " is-auto" : "");
    var hint = f.hint ? '<div class="hint">' + esc(f.hint) + '</div>' : "";
    var dot = f.chip ? '<i class="dot"></i>' : "";
    if (f.type === "textarea")
      return '<div class="' + cls + '"><label for="f_' + id + '">' + lab + '</label><textarea id="f_' + id + '" data-id="' + id + '" placeholder="' + esc(f.placeholder || "") + '">' + esc(v || "") + '</textarea></div>';
    if (f.type === "text")
      return '<div class="' + cls + '"><label for="f_' + id + '">' + lab + '</label><input type="text" id="f_' + id + '" data-id="' + id + '" value="' + esc(v || "") + '" placeholder="' + esc(f.placeholder || "") + '"></div>';
    if (f.type === "date")
      return '<div class="' + cls + '"><label for="f_' + id + '">' + lab + '</label><input type="date" id="f_' + id + '" data-id="' + id + '" value="' + esc(v || "") + '"></div>';
    if (f.type === "toggle")
      return '<div class="' + cls + '"><label class="switch"><input type="checkbox" data-id="' + id + '" data-toggle="1"' + (v === 0 || v === false ? "" : " checked") + '>' + lab + '</label>' + hint + '</div>';
    // num
    return '<div class="' + cls + '"><label for="f_' + id + '">' + dot + lab + '</label>' +
      '<div class="inp"><input id="f_' + id + '" data-id="' + id + '" data-num="1" inputmode="decimal" autocomplete="off" placeholder="' + (f.opt ? "0" : "") + '" value="' + (v === undefined ? "" : esc(v)) + '"><span class="unit">' + esc(f.unit || "") + '</span></div>' +
      hint + '<div class="auto">자동 제안값 · 수정할 수 있어요</div></div>';
  }

  function sectorStat() {
    if (!peers || !A.sector || A.sector === "none") return null;
    var s = peers.sectors.filter(function (x) { return x.id === A.sector; })[0];
    if (!s) return null;
    var st = { beta: null };
    if (s.stats && s.stats.evEbitda) st.evEbitda = Object.assign({ source: s.name + " 상장사 " + s.stats.evEbitda.n + "곳의 25%/중앙값/75%" }, s.stats.evEbitda);
    if (s.stats && s.stats.per) st.per = s.stats.per;
    return st;
  }
  function sectorById(id) { return peers ? peers.sectors.filter(function (x) { return x.id === id; })[0] : null; }

  function peerPreview(id) {
    var s = sectorById(id);
    if (!s) return '<div class="peer-preview">이 업종은 기본 범위(보수 6배 · 기본 8배 · 낙관 10배)를 쓰고, 결과 화면에서 직접 조정할 수 있어요.</div>';
    var ev = s.stats && s.stats.evEbitda, per = s.stats && s.stats.per;
    var names = s.peers.slice(0, 6).map(function (p) { return esc(p.name); }).join(" · ");
    var line = ev ? ("피어 " + ev.n + "곳 EV/EBITDA <b>" + ev.down + " / " + ev.base + " / " + ev.up + "배</b>" + (per ? " · PER <b>" + per.down + " / " + per.base + " / " + per.up + "배</b>" : "") + " (25%/중앙값/75%)")
                    : "아직 이 업종의 배수가 수집되지 않아 기본 범위(6/8/10배)로 계산해요. 수집되면 자동으로 바뀝니다.";
    return '<div class="peer-preview"><b>비교 상장사:</b> ' + names + '<br>' + line + '</div>';
  }

  function renderQ() {
    var q = Q[step];
    applyDefaults(q);
    var pctDone = Math.round(step / N * 100);
    var body = "";

    if (q.custom === "sector") {
      var sectors = peers ? peers.sectors : [];
      var sug = Survey.suggestSectors((A.name || "") + " " + (A.biz || ""), sectors).slice(0, 3);
      if (A.sector === undefined && sug.length) { A.sector = sug[0].id; auto.sector = true; }
      body += '<div class="choice">' + sug.map(function (s, i) {
        return '<button type="button" class="opt' + (A.sector === s.id ? " on" : "") + '" data-sector="' + s.id + '"><b>' + esc(s.name) + (i === 0 ? ' <span class="badge">추천</span>' : "") + '</b><span class="d">사업 설명 속 "' + esc(s.hits.slice(0, 3).join('", "')) + '" 등과 일치</span></button>';
      }).join("") + '</div>';
      body += '<div class="field sector-more"><label for="sectorSel">' + (sug.length ? "다른 업종에서 고르기" : "업종 고르기") + '</label><select id="sectorSel"><option value="">선택하세요</option>' +
        sectors.map(function (s) { return '<option value="' + s.id + '"' + (A.sector === s.id ? " selected" : "") + '>' + esc(s.name) + '</option>'; }).join("") +
        '<option value="none"' + (A.sector === "none" ? " selected" : "") + '>해당 업종 없음 (기본 범위 사용)</option></select></div>';
      body += '<div id="peerBox">' + (A.sector ? peerPreview(A.sector) : "") + '</div>';
    } else if (q.custom === "growth") {
      if (!A.growthPreset) A.growthPreset = "normal";
      var gp = Survey.GROWTH_PRESETS;
      body += '<div class="choice">' + Object.keys(gp).map(function (k) {
        var p = gp[k];
        return '<button type="button" class="opt' + (A.growthPreset === k ? " on" : "") + '" data-growth="' + k + '"><b>' + p.label + '</b><span class="d">' + p.desc + ' — 기본 시나리오 3~5년차 매출 성장률 ' + p.base.join("% · ") + '%</span></button>';
      }).join("") + '</div>';
    } else if (q.custom === "choice") {
      var f0 = q.fields[0];
      body += '<div class="choice">' + f0.opts.map(function (o) {
        return '<button type="button" class="opt' + (A[f0.id] === o.v ? " on" : "") + '" data-choice="' + o.v + '"><b>' + esc(o.label) + '</b><span class="d">' + esc(o.desc) + '</span></button>';
      }).join("") + '</div>';
    } else {
      var fields = q.fields.slice();
      if (q.order) fields = q.order.map(function (id) { return fields.filter(function (f) { return f.id === id; })[0]; });
      var allNum = fields.every(function (f) { return f.type === "num"; });
      var layout = !STACK[q.id] && allNum && fields.length === 3 ? "g3" : !STACK[q.id] && allNum && fields.length === 2 ? "g2" : "";
      body += '<div class="fields ' + layout + '">' + fields.map(fieldHtml).join("") + '</div>';
    }

    var where = (q.where || (q.docs && q.docs.length)) ?
      '<div class="where">' + (q.where ? '<b>어디서 찾나요?</b> ' + esc(q.where) : '') + (q.docs && q.docs.length ? (q.where ? '<br>' : '') + '<b>참고 자료:</b> ' + esc(q.docs.join(" · ")) : '') + '</div>' : "";

    app.innerHTML =
      '<div class="progress"><div class="progress-top"><span><span class="sec">' + esc(q.section) + '</span></span><span>' + (step + 1) + ' / ' + N + '</span></div><div class="bar"><i style="width:' + pctDone + '%"></i></div></div>' +
      '<div class="q-card" id="qcard"><h2>' + esc(res(q.title)) + '</h2><p class="desc">' + esc(res(q.desc)) + '</p>' + body + where +
      '<div id="errBox">' + errHtml() + '</div>' +
      '<div class="nav-btns"><button class="btn ghost" id="prev">← 이전</button><div class="right">' +
      '<button class="btn primary" id="next">' + (step === N - 1 ? "결과 보기" : "다음") + '</button></div></div></div>';

    bindQ(q);
    var first = app.querySelector("input[data-num], textarea, input[type=text], input[type=date]");
    if (first && !q.custom) setTimeout(function () { try { first.focus({ preventScroll: true }); } catch (e) { first.focus(); } }, 50);
  }

  function errHtml() { return errs.length ? '<div class="errs">' + errs.map(function (m) { return '<div>' + esc(m) + '</div>'; }).join("") + '</div>' : ""; }

  function bindQ(q) {
    document.getElementById("prev").onclick = function () { collectGoto(step - 1, false); };
    document.getElementById("next").onclick = function () { collectGoto(step + 1, true); };
    app.querySelectorAll("[data-id]").forEach(function (el) {
      el.addEventListener("input", function () {
        var id = el.dataset.id;
        if (el.dataset.toggle) { A[id] = el.checked ? 1 : 0; save(); return; }
        if (el.dataset.num) { var v = parseNum(el.value); if (v === undefined) delete A[id]; else A[id] = v; }
        else A[id] = el.value;
        auto[id] = false;
        el.closest(".field").classList.remove("is-auto");
        refreshAuto(q, id);
        save();
      });
      el.addEventListener("keydown", function (e) {
        if (e.key === "Enter" && el.tagName !== "TEXTAREA") { e.preventDefault(); collectGoto(step + 1, true); }
      });
    });
    app.querySelectorAll("[data-sector]").forEach(function (b) { b.onclick = function () { setSector(b.dataset.sector); }; });
    var sel = document.getElementById("sectorSel");
    if (sel) sel.onchange = function () { if (sel.value) setSector(sel.value); };
    app.querySelectorAll("[data-growth]").forEach(function (b) { b.onclick = function () { A.growthPreset = b.dataset.growth; save(); renderQ(); }; });
    app.querySelectorAll("[data-choice]").forEach(function (b) { b.onclick = function () { A[q.fields[0].id] = b.dataset.choice; save(); renderQ(); }; });
  }

  // 같은 화면의 자동 제안값을 입력 중에 갱신
  function refreshAuto(q, changedId) {
    (q.fields || []).forEach(function (f) {
      if (!f.def || f.id === changedId || !auto[f.id]) return;
      var v = f.def(A), el = document.getElementById("f_" + f.id);
      if (!el) return;
      var has = v !== undefined && isFinite(v) && v !== 0;
      if (has) { A[f.id] = v; el.value = v; } else { delete A[f.id]; el.value = ""; }
      var fld = el.closest(".field"); if (fld) fld.classList.toggle("is-auto", has);
    });
  }

  function setSector(id) {
    A.sector = id; auto.sector = false; save();
    renderQ();
  }

  function collectGoto(target, validate) {
    if (validate) {
      var q = Q[step];
      errs = Survey.validate(q, A);
      if (errs.length) { document.getElementById("errBox").innerHTML = errHtml(); return; }
    }
    if (target < 0) { goto(-1); return; }
    goto(target);
  }

  // ── 결과 화면 ──
  function compute() {
    var stat = sectorStat();
    var model = Survey.buildModel(A, stat, adv);
    var R = DCF.runAll(model);
    var mc = Survey.multipleChecks(model, stat, A);
    return { stat: stat, model: model, R: R, mc: mc };
  }

  function renderResult() {
    var C;
    try { C = compute(); } catch (e) { app.innerHTML = '<div class="empty">계산 중 오류가 발생했어요. 입력값을 확인해 주세요.<br><br><button class="btn" id="back">← 마지막 질문으로</button></div>'; document.getElementById("back").onclick = function () { goto(N - 1); }; return; }
    var R = C.R, M = C.model, mc = C.mc;
    var share = Survey.num(A, "share"); share = isFinite(share) ? share : 100;
    var title = (A.name ? A.name + " " : "") + "기업가치 간이평가";
    var hope = Survey.n0(A, "hopePrice") * 100;
    var eqB = R.base.equity, eqD = R.down.equity, eqU = R.up.equity;

    var chips = '<span class="chip2">영업가치(EV) ' + eok(R.base.ev, 0) + '</span>' +
      '<span class="chip2">정상화 EBITDA ' + eok(R.base.normEbitdaLast, 1) + ' 대비 EV ' + mx(R.base.evToLast) + '</span>';
    if (share < 100) chips += '<span class="chip2">지분 ' + share + '% 환산 ' + eok(eqB * share / 100, 0) + '</span>';
    if (hope > 0) { var diff = hope / eqB - 1; chips += '<span class="chip2">희망가 ' + eok(hope, 0) + ' = 기본 대비 ' + (diff >= 0 ? "+" : "") + Math.round(diff * 100) + '%</span>'; }

    var html =
      '<div class="res-head"><h1>' + esc(title) + '</h1><p>기준일 ' + esc(A.baseDate) + ' · 지분 100% 기준 · 단위 억원 · 참고용 간이평가</p></div>' +
      '<div class="notice-strong top">⚠️ <b>간이평가 결과</b>입니다. 단순 입력 사항을 기반으로 한 추정치이며, <b>실제 매각가격과 차이가 있을 수 있습니다.</b></div>' +
      '<div class="res-hero"><div class="k">예상 매도가격 (기본 시나리오) · 간이평가</div>' +
        '<div class="big">' + eok(eqB, 0).replace(/억$/, '<small>억원</small>').replace(/조$/, '<small>조원</small>') + '</div>' +
        '<div class="rng">보수 ' + eok(eqD, 0) + ' ~ 낙관 ' + eok(eqU, 0) + '</div><div class="chips">' + chips + '</div></div>';

    html += ffSection(C, hope);
    html += scenSection(C);
    html += bridgeSection(C);
    html += projSection(C);
    html += sensSection(C);
    html += peerSection(C);
    html += advSection(C);

    var warns = M.meta.warnings.slice();
    if (!C.stat || !C.stat.evEbitda) warns.push("업종 피어 배수가 아직 없어 Exit 배수를 기본 범위(6/8/10배)로 썼어요. 아래 '가정 보기·조정'에서 직접 바꿀 수 있어요.");
    if (R.base.tvShare > 0.75) warns.push("기본 시나리오 가치의 " + Math.round(R.base.tvShare * 100) + "%가 5년 이후(터미널) 가치예요. 장기 가정에 민감하니 민감도 표를 함께 보세요.");
    if (warns.length) html += '<div class="warn"><b>확인이 필요한 점</b><br>' + warns.map(function (w) { return "· " + esc(w); }).join("<br>") + '</div>';

    html += '<div class="disclaimer strong"><b>※ 간이평가 안내:</b> 본 결과는 입력하신 값과 일반적인 평가 가정으로 계산한 <b>참고용 간이평가</b>이며 가치평가 보고서·투자 자문이 아닙니다. 실제 거래가격은 실사, 거래구조(지분율·어닝아웃 등), 세금, 협상에 따라 크게 달라질 수 있어요. 할인율 요소와 세율, 배수는 판단값이므로 전문가와 검증하세요.</div>';
    html += '<div class="res-actions"><button class="btn" id="aEdit">입력값 수정하기</button><button class="btn" id="aJson">입력값 내려받기</button><button class="btn" id="aPrint">인쇄 / PDF 저장</button><button class="btn ghost" id="aReset">처음부터 다시</button></div>';

    var wasOpen = document.getElementById("advBox") && document.getElementById("advBox").open;
    app.innerHTML = html;
    if (wasOpen) document.getElementById("advBox").open = true;
    bindResult();
  }

  function ffSection(C, hope) {
    var R = C.R, mc = C.mc;
    var rows = [{ lab: "DCF (현금흐름할인)", sub: "보수 ~ 낙관", lo: R.down.equity, mid: R.base.equity, hi: R.up.equity, cls: "" }];
    if (mc.evEbitda) rows.push({ lab: "EV/EBITDA 배수법", sub: mc.evEbitda.mult.down + " ~ " + mc.evEbitda.mult.up + "배", lo: mc.evEbitda.equity.down, mid: mc.evEbitda.equity.base, hi: mc.evEbitda.equity.up, cls: "alt" });
    if (mc.per) rows.push({ lab: "PER 배수법", sub: mc.per.mult.down + " ~ " + mc.per.mult.up + "배", lo: mc.per.equity.down, mid: mc.per.equity.base, hi: mc.per.equity.up, cls: "alt2" });
    var vals = [];
    rows.forEach(function (r) { vals.push(r.lo, r.hi); });
    if (hope > 0) vals.push(hope);
    var lo = Math.min.apply(null, vals) * 0.85, hi = Math.max.apply(null, vals) * 1.08;
    if (lo < 0) lo = Math.min(0, lo);
    function pos(v) { return Math.max(0, Math.min(100, (v - lo) / (hi - lo) * 100)); }
    var out = '<div class="section"><h3>가격 범위 한눈에 보기</h3><p class="sub">지분가치(100%) 기준. 막대는 보수~낙관 범위, 검은 선은 기본값이에요.' + (mc.evEbitda || mc.per ? "" : " 업종 배수 데이터가 수집되면 배수법도 함께 표시돼요.") + '</p><div class="ff">';
    rows.forEach(function (r) {
      out += '<div class="ff-row"><div class="lab">' + r.lab + '<span>' + eok(r.lo, 0) + ' ~ ' + eok(r.hi, 0) + ' · ' + r.sub + '</span></div><div class="ff-track">' +
        '<div class="ff-bar ' + r.cls + '" style="left:' + pos(r.lo) + '%;width:' + Math.max(0.8, pos(r.hi) - pos(r.lo)) + '%"></div>' +
        '<div class="ff-mark" style="left:calc(' + pos(r.mid) + '% - 1px)"></div>' +
        (hope > 0 ? '<div class="ff-hope" style="left:' + pos(hope) + '%"></div>' : '') + '</div></div>';
    });
    out += '</div><div class="ff-axis"><span>' + eok(lo, 0) + '</span><span>' + eok((lo + hi) / 2, 0) + '</span><span>' + eok(hi, 0) + '</span></div>';
    if (hope > 0) out += '<div class="ff-legend"><span><i style="border-left:2px dashed var(--sell);height:10px;width:0;background:none"></i>희망가 ' + eok(hope, 0) + '</span></div>';
    return out + '</div>';
  }

  function scenSection(C) {
    var names = { down: "보수", base: "기본", up: "낙관" };
    var s = '<div class="section"><h3>시나리오별 결과</h3><p class="sub">매출·수익성·할인율·종료 배수를 달리한 세 가지 가정이에요.</p><div class="scen-grid">';
    ["down", "base", "up"].forEach(function (k) {
      var r = C.R[k], sc = C.model.scenarios[k];
      s += '<div class="scen ' + k + '"><h4><i class="dot"></i>' + names[k] + '</h4><div class="eq">' + eok(r.equity, 0).replace(/억$/, "<small>억원</small>") + '</div>' +
        '<dl><dt>영업가치(EV)</dt><dd>' + eok(r.ev, 0) + '</dd>' +
        '<dt>EV/정상화EBITDA</dt><dd>' + mx(r.evToLast) + '</dd>' +
        '<dt>할인율(WACC)</dt><dd>' + pc(sc.wacc) + '</dd>' +
        '<dt>영구성장률</dt><dd>' + pc(sc.g) + '</dd>' +
        '<dt>종료 배수</dt><dd>' + mx(sc.exit) + '</dd>' +
        '<dt>터미널 비중</dt><dd>' + pc(r.tvShare, 0) + '</dd></dl></div>';
    });
    return s + '</div></div>';
  }

  function bridgeSection(C) {
    var r = C.R.base, b = C.model.common.bridge;
    function row(l, v, neg) { return '<tr><td>' + l + '</td><td class="' + (neg || v < 0 ? "neg" : "") + '">' + (v < 0 ? "-" : "") + eok(Math.abs(v), 1) + '</td></tr>'; }
    var t = '<div class="section"><h3>가치가 어떻게 쌓이나요? (기본 시나리오)</h3><p class="sub">영업으로 번 돈의 가치(EV)에서 빚을 빼고 현금·영업 외 자산을 더하면 주주 몫(지분가치)이 돼요.</p><div class="tscroll"><table class="t"><tbody>';
    t += row("영업가치 (EV)", r.ev);
    t += row("(+) 현금·금융자산", b.cash + b.finAssets);
    t += row("(−) 금융차입금", -b.debt);
    t += row("(−) 퇴직급여채무·미지급세금·최소현금", -(b.retire + b.taxPayable + b.minCash));
    t += row("(+) 비영업자산 순액", r.nonOp);
    t += '<tr class="tot"><td>지분가치 (100%)</td><td>' + eok(r.equity, 1) + '</td></tr></tbody></table></div></div>';
    return t;
  }

  function projSection(C) {
    var rows = C.R.base.rows, y0 = Survey.curYear(A);
    var head = '<tr><th></th>' + rows.map(function (_, i) { return '<th>' + (y0 + i) + 'E</th>'; }).join("") + '</tr>';
    function line(lab, key, fmt) { return '<tr><td>' + lab + '</td>' + rows.map(function (r) { return '<td>' + (fmt ? fmt(r[key]) : eok(r[key], 1)) + '</td>'; }).join("") + '</tr>'; }
    var t = '<div class="section"><h3>5년 추정 (기본 시나리오)</h3><p class="sub">정상화 EBITDA는 장부 EBITDA에 대표 보수 초과분 등 인수 후 사라질 비용을 더한 값이에요.</p><div class="tscroll"><table class="t"><thead>' + head + '</thead><tbody>' +
      line("매출", "rev") + line("장부 EBITDA", "ebitdaRep") + line("(+) 정상화 가산", "addback") + line("정상화 EBITDA", "normEbitda") +
      line("세후 영업이익(NOPAT)", "nopat") + line("잉여현금흐름(FCF)", "fcf") + '</tbody></table></div></div>';
    return t;
  }

  function heat(v, lo, hi) {
    var t = hi > lo ? (v - lo) / (hi - lo) : 0.5;
    return 'background:rgba(52,87,224,' + (0.06 + 0.26 * t).toFixed(2) + ')';
  }
  function sensTable(C, rowKey, rowVals, rowLab, colKey, colVals, colLab, rowFmt, colFmt) {
    var grid = DCF.sensitivity(C.model.common, C.model.scenarios.base, rowKey, rowVals, colKey, colVals, "equity");
    var flat = [].concat.apply([], grid), lo = Math.min.apply(null, flat), hi = Math.max.apply(null, flat);
    var h = '<div class="tscroll"><table class="t sens"><thead><tr><th>' + rowLab + ' \\ ' + colLab + '</th>' + colVals.map(function (c) { return '<th>' + colFmt(c) + '</th>'; }).join("") + '</tr></thead><tbody>';
    grid.forEach(function (rw, i) {
      h += '<tr><th>' + rowFmt(rowVals[i]) + '</th>' + rw.map(function (v, j) {
        return '<td class="' + (i === 2 && j === 2 ? "mid" : "") + '" style="' + heat(v, lo, hi) + '">' + eok(v, 0).replace("억", "") + '</td>';
      }).join("") + '</tr>';
    });
    return h + '</tbody></table></div>';
  }
  function sensSection(C) {
    var sc = C.model.scenarios.base;
    var w = [-0.02, -0.01, 0, 0.01, 0.02].map(function (d) { return sc.wacc + d; });
    var g = [-0.01, -0.005, 0, 0.005, 0.01].map(function (d) { return sc.g + d; });
    var e = [-2, -1, 0, 1, 2].map(function (d) { return Math.max(1, sc.exit + d); });
    return '<div class="section"><h3>가정이 바뀌면 얼마나 달라지나요?</h3><p class="sub">기본 시나리오 지분가치(억원). 테두리 칸이 현재 가정이에요.</p>' +
      '<div class="sens-title">할인율(WACC) × 영구성장률</div>' + sensTable(C, "wacc", w, "WACC", "g", g, "성장률", function (x) { return pc(x); }, function (x) { return pc(x); }) +
      '<div class="sens-title">할인율(WACC) × 종료 EV/EBITDA 배수</div>' + sensTable(C, "wacc", w, "WACC", "exit", e, "배수", function (x) { return pc(x); }, function (x) { return mx(x); }) + '</div>';
  }

  function peerSection(C) {
    var s = sectorById(A.sector);
    if (!s) return '<div class="section"><h3>업종 피어 비교</h3><p class="sub">업종을 선택하지 않아 기본 배수 범위(6/8/10배)를 사용했어요. 입력값 수정에서 업종을 고르면 비교 상장사가 표시돼요.</p></div>';
    var ev = s.stats && s.stats.evEbitda, per = s.stats && s.stats.per;
    var t = '<div class="section"><h3>업종 피어 비교 · ' + esc(s.name) + '</h3><p class="sub">' +
      (ev ? "상장사 " + ev.n + "곳의 EV/EBITDA 25%·중앙값·75% = " + ev.down + " · " + ev.base + " · " + ev.up + "배를 보수·기본·낙관 종료 배수로 썼어요." : "아직 이 업종의 배수를 수집하지 못해 기본 범위를 썼어요.") +
      (peers && peers.updated ? " (데이터 기준 " + peers.updated + ")" : "") + '</p>' +
      '<div class="tscroll"><table class="t"><thead><tr><th>회사</th><th>시가총액</th><th>EV/EBITDA</th><th>PER</th></tr></thead><tbody>';
    s.peers.forEach(function (p) {
      var nm = esc(p.name) + (p.dart_name && p.dart_name.replace(/\s|\(주\)|주식회사/g, "") !== p.name.replace(/\s/g, "") ? ' <span class="peer-tag">(DART: ' + esc(p.dart_name) + ')</span>' : "");
      t += '<tr><td>' + nm + '</td><td>' + (p.mcap_eok ? p.mcap_eok.toLocaleString("ko-KR") + "억" : "-") + '</td><td>' + (p.evEbitda ? p.evEbitda + "x" : "-") + '</td><td>' + (p.per ? p.per + "x" : "-") + '</td></tr>';
    });
    return t + '</tbody></table></div></div>';
  }

  function advSection(C) {
    var M = C.model, m = M.meta, w = M.wacc, p = m.prem;
    function pf(id, label, val, unit) { return '<div class="field"><label>' + label + '</label><div class="inp"><input data-adv="' + id + '" inputmode="decimal" value="' + val + '"><span class="unit">' + unit + '</span></div></div>'; }
    var h = '<details class="adv" id="advBox"><summary>가정 보기 · 조정</summary><div class="body">';
    h += '<div class="adv-row-title">할인율(자기자본비용) 구성</div><div class="tscroll"><table class="t"><tbody>' +
      '<tr><td>무위험이자율 (국고채 10년, ' + esc(Survey.CONFIG.rfAsOf) + ' 기준)</td><td>' + pc(m.rf, 2) + '</td></tr>' +
      '<tr><td>베타 × 시장위험프리미엄 (' + m.beta + ' × ' + pc(Survey.CONFIG.mrp) + ')</td><td>' + pc(m.beta * Survey.CONFIG.mrp, 2) + '</td></tr>' +
      '<tr><td>규모 프리미엄 (최근 매출 ' + (m.rev3 / 100).toLocaleString("ko-KR") + '억 기준)</td><td>' + pc(p.size, 2) + '</td></tr>' +
      '<tr><td>거래처 집중 (최대 거래처 ' + Survey.n0(A, "top1") + '%)</td><td>' + pc(p.cust, 2) + '</td></tr>' +
      '<tr><td>대표 의존도</td><td>' + pc(p.ceoDep, 2) + '</td></tr>' +
      '<tr><td>이익 변동성' + (p.volWhy ? " (" + esc(p.volWhy) + ")" : "") + '</td><td>' + pc(p.vol, 2) + '</td></tr>' +
      '<tr class="tot"><td>적용 할인율 (기본, 0.1% 반올림)</td><td>' + pc(w.applied, 1) + '</td></tr></tbody></table></div>';
    h += '<div class="adv-row-title">직접 조정 (비워두면 기본값)</div><div class="adv-grid">' +
      pf("rf", "무위험이자율", +(m.rf * 100).toFixed(3), "%") + pf("beta", "베타", m.beta, "") + pf("taxRate", "법인세율", +(m.taxRate * 100).toFixed(1), "%") + '</div>';
    h += '<div class="adv-grid">' + pf("g.down", "영구성장률 · 보수", +(m.g.down * 100).toFixed(2), "%") + pf("g.base", "영구성장률 · 기본", +(m.g.base * 100).toFixed(2), "%") + pf("g.up", "영구성장률 · 낙관", +(m.g.up * 100).toFixed(2), "%") + '</div>';
    h += '<div class="adv-grid">' + pf("exit.down", "종료 배수 · 보수", m.exit.down, "x") + pf("exit.base", "종료 배수 · 기본", m.exit.base, "x") + pf("exit.up", "종료 배수 · 낙관", m.exit.up, "x") + '</div>';
    h += '<div class="adv-grid">' + pf("wGordon", "영구성장 방식 가중치", +(m.wGordon * 100).toFixed(0), "%") + '</div>';
    h += '<ul class="note-list"><li>종료 배수 출처: ' + esc(m.exitSource) + '</li><li>종료가치는 영구성장 방식과 종료 배수 방식을 ' + Math.round(m.wGordon * 100) + ':' + Math.round((1 - m.wGordon) * 100) + '로 섞어요.</li>' +
      '<li>시나리오별 할인율 가감: 보수 ' + (m.waccAdj.down >= 0 ? "+" : "") + pc(m.waccAdj.down) + ' · 낙관 ' + pc(m.waccAdj.up) + '</li>' +
      '<li>대표 보수 초과분 ' + eok(m.ceoExcess, 1) + ' · 가족 보수 ' + eok(m.family, 1) + ' 를 정상화에 반영(보수 시나리오는 대표 초과분만, 개인성 비용은 기본 50%·낙관 100%·보수 0%).</li>' +
      '<li>운전자본 회전일(기본): 매출채권 ' + Math.round(m.wcDays.base.dso) + '일 · 재고 ' + Math.round(m.wcDays.base.dio) + '일 · 매입채무 ' + Math.round(m.wcDays.base.dpo) + '일.</li>' +
      '<li>결산월은 12월로 가정했고, 당해 연도 현금흐름은 기준일 이후 기간만 반영해요.</li></ul>';
    h += '<div class="res-actions"><button class="btn" id="advReset">기본 가정으로 되돌리기</button></div>';
    return h + '</div></details>';
  }

  function bindResult() {
    document.getElementById("aEdit").onclick = function () { goto(0); };
    document.getElementById("aReset").onclick = function () { resetAll(); goto(-1); };
    document.getElementById("aPrint").onclick = function () { var d = document.getElementById("advBox"); if (d) d.open = true; window.print(); };
    document.getElementById("aJson").onclick = function () {
      var blob = new Blob([JSON.stringify({ answers: A, adjustments: adv }, null, 1)], { type: "application/json" });
      var a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "valuation-input.json"; a.click();
      setTimeout(function () { URL.revokeObjectURL(a.href); }, 500);
    };
    var ar = document.getElementById("advReset");
    if (ar) ar.onclick = function () { adv = { g: {}, exit: {} }; save(); renderResult(); };
    app.querySelectorAll("[data-adv]").forEach(function (el) {
      el.addEventListener("change", function () {
        var key = el.dataset.adv, v = parseNum(el.value);
        if (v !== undefined && !isFinite(v)) return;
        var isPct = /^(rf|taxRate|wGordon|g\.)/.test(key);
        var val = v === undefined ? undefined : (isPct ? v / 100 : v);
        if (key.indexOf(".") > 0) { var a = key.split("."); adv[a[0]] = adv[a[0]] || {}; if (val === undefined) delete adv[a[0]][a[1]]; else adv[a[0]][a[1]] = val; }
        else { if (val === undefined) delete adv[key]; else adv[key] = val; }
        save(); renderResult();
      });
    });
  }

  // ── 시작 ──
  fetch("peers.json?t=" + Date.now()).then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; })
    .then(function (p) {
      peers = p && p.sectors ? p : { sectors: [] };
      if (!load()) { A.baseDate = today(); }
      if (!A.baseDate) A.baseDate = today();
      if (step >= N) renderResult();
      else renderIntro();
    });
})();
