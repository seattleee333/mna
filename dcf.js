/* 간이 DCF 계산 엔진 (브라우저/Node 공용)
 * 단위: 백만원. 입력값은 모두 이 파일 밖(survey.js)에서 억원→백만원으로 환산해서 넘긴다.
 * 구조는 실무용 DCF 엑셀(정상화 EBITDA → NOPAT → FCF → 터미널가치 → EV → 지분가치)과 동일하다.
 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.DCF = factory();
})(typeof self !== "undefined" ? self : this, function () {
  var DAY = 86400000;

  function roundTo(x, d) { var p = Math.pow(10, d); return Math.round(x * p) / p; }

  // 평가기준일 ~ 당해 결산일(12/31)까지 남은 기간 비율 (당해 FCF 중 기준일 이후 귀속분)
  function stubFraction(baseDate) {
    var fyEnd = new Date(Date.UTC(baseDate.getUTCFullYear(), 11, 31));
    var b = new Date(Date.UTC(baseDate.getUTCFullYear(), baseDate.getUTCMonth(), baseDate.getUTCDate()));
    return Math.max(0, (fyEnd - b) / DAY / 365);
  }

  // 할인율: 자기자본비용 build-up. 무차입이면 WACC = Ke
  function buildWacc(w) {
    var ke = w.rf + w.beta * w.mrp + w.size + w.specific;
    var dw = w.debtWeight || 0;
    var kd = w.kd == null ? 0.06 : w.kd;
    var raw = ke * (1 - dw) + kd * (1 - (w.tax == null ? 0.22 : w.tax)) * dw;
    return { ke: ke, raw: raw, applied: roundTo(raw, 3) };
  }

  /* c: 공통 가정, s: 시나리오 가정, ov: 민감도용 덮어쓰기 {wacc, g, exit}
   * c = { stub, taxRate, mid(0|1), termCapexRatio, actual:{ebitda,ar,inv,ap}, uncertainLast, uncertainFwd, bridge:{...} }
   * s = { rev:[5], margin:[5](보고 EBITDA 마진), addbackFixed, uncertainRatio, da, capex,
   *       dso, dio, dpo, wacc, g, exit, wGordon }
   */
  function runScenario(c, s, ov) {
    ov = ov || {};
    var wacc = ov.wacc != null ? ov.wacc : s.wacc;
    var g = ov.g != null ? ov.g : s.g;
    var exit = ov.exit != null ? ov.exit : s.exit;
    var t = c.taxRate;
    var n = s.rev.length;
    var mid = c.mid ? 1 : 0;

    var addbackFwd = s.addbackFixed + s.uncertainRatio * c.uncertainFwd;
    var addbackLast = s.addbackFixed + s.uncertainRatio * c.uncertainLast;

    var rows = [];
    var prevNwc = c.actual.ar + c.actual.inv - c.actual.ap;
    var pvFlows = 0, endT = 0;
    for (var i = 0; i < n; i++) {
      var rev = s.rev[i];
      var ebitdaRep = rev * s.margin[i];
      var normEbitda = ebitdaRep + addbackFwd;
      var ebit = normEbitda - s.da;
      var tax = Math.max(0, ebit) * t;
      var nopat = ebit - tax;
      var cashCost = rev - ebitdaRep;
      var ar = rev * s.dso / 365;
      var inv = cashCost * s.dio / 365;
      var ap = cashCost * s.dpo / 365;
      var nwc = ar + inv - ap;
      var dNwc = -(nwc - prevNwc);
      var fcf = nopat + s.da - s.capex + dNwc;
      var frac = i === 0 ? c.stub : 1;
      endT = i === 0 ? c.stub : endT + 1;
      var discT = endT - mid * 0.5 * frac;
      var df = 1 / Math.pow(1 + wacc, discT);
      var pv = fcf * frac * df;
      pvFlows += pv;
      rows.push({ rev: rev, ebitdaRep: ebitdaRep, addback: addbackFwd, normEbitda: normEbitda, da: s.da,
                  ebit: ebit, tax: tax, nopat: nopat, capex: s.capex, nwc: nwc, dNwc: dNwc, fcf: fcf,
                  frac: frac, endT: endT, discT: discT, df: df, pv: pv });
      prevNwc = nwc;
    }

    var last = rows[n - 1];
    var termBase = (last.normEbitda - last.da) * (1 - t) + last.da * (1 - c.termCapexRatio);
    var termFcf = termBase * (1 + g) - g * last.nwc;
    var gordonTV = wacc > g ? termFcf / (wacc - g) : NaN;
    var exitTV = last.normEbitda * exit;
    var pvGordon = gordonTV / Math.pow(1 + wacc, endT - mid * 0.5);
    var pvExit = exitTV / Math.pow(1 + wacc, endT);
    var evGordon = pvFlows + pvGordon;
    var evExit = pvFlows + pvExit;
    var wG = s.wGordon;
    var ev = wG * evGordon + (1 - wG) * evExit;

    var b = c.bridge;
    var nonOp = b.nonOpInclude ? (b.nonOpAssets - b.nonOpLiabs - b.nonOpTax) : 0;
    var equityOperating = ev + b.cash + b.finAssets - b.debt - b.retire - b.taxPayable - b.minCash;
    var equity = equityOperating + nonOp;

    var normEbitdaLast = c.actual.ebitda + addbackLast; // 최근 확정연도 정상화 EBITDA
    return {
      rows: rows, pvFlows: pvFlows, gordonTV: gordonTV, exitTV: exitTV, pvGordon: pvGordon, pvExit: pvExit,
      evGordon: evGordon, evExit: evExit, ev: ev, equityOperating: equityOperating, nonOp: nonOp, equity: equity,
      tvShare: (wG * pvGordon + (1 - wG) * pvExit) / ev,
      impliedMultipleGordon: gordonTV / last.normEbitda,
      impliedGrowthExit: (exitTV * wacc - termBase) / (exitTV + termBase - last.nwc),
      addbackFwd: addbackFwd, addbackLast: addbackLast,
      normEbitdaLast: normEbitdaLast,
      evToLast: ev / normEbitdaLast,
      evToFirst: ev / rows[0].normEbitda,
      evToSecond: ev / rows[1].normEbitda,
      params: { wacc: wacc, g: g, exit: exit, wGordon: wG }
    };
  }

  // 민감도 표: rowVals × colVals 에서 metric('ev'|'equity') 계산
  function sensitivity(c, s, rowKey, rowVals, colKey, colVals, metric) {
    return rowVals.map(function (rv) {
      return colVals.map(function (cv) {
        var ov = {}; ov[rowKey] = rv; ov[colKey] = cv;
        var r = runScenario(c, s, ov);
        return r[metric || "equity"];
      });
    });
  }

  function runAll(model) {
    var out = {};
    ["base", "up", "down"].forEach(function (k) { out[k] = runScenario(model.common, model.scenarios[k]); });
    return out;
  }

  return { buildWacc: buildWacc, stubFraction: stubFraction, runScenario: runScenario, runAll: runAll,
           sensitivity: sensitivity, roundTo: roundTo };
});
