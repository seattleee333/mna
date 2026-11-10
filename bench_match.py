"""AI 매칭 채점기 — 과거 실제 인수 사례로 매칭 품질을 잰다.

방식: 최근 5년 타법인 취득 사례(계열사·해외 법인 출자 제외) 하나하나에 대해
      '대상 회사의 사업 설명'을 매도 기업 정보처럼 넣고, 실제 인수자가 결과 몇 위에 나오는지 본다.
      그 사례 자체는 인수 이력·업종 인수 패턴 계산에서 빼고(leave-one-out) 돌린다.
지표: 상위 10/30/100위 안에 실제 인수자가 든 비율, 중앙 순위.

사용: python3 bench_match.py [--n 400] [--tweak '{"trans":0}']   (로컬 http.server 8765 가 떠 있어야 함)
"""
import sys
import json
import argparse
import statistics
from playwright.sync_api import sync_playwright

ap = argparse.ArgumentParser()
ap.add_argument("--n", type=int, default=0, help="표본 수(0이면 전체)")
ap.add_argument("--tweak", default="{}", help="window.MNA_TWEAK 로 넘길 설정(JSON)")
ap.add_argument("--port", type=int, default=8765)
ap.add_argument("--label", default="")
ap.add_argument("--out", default="bench_last.json")
args = ap.parse_args()

JS = r"""
async ([tweak, n]) => {
  window.MNA_TWEAK = tweak;
  const M = window.MNA_MATCH;
  await M.load(); await M.loadCases();
  const view = await (await fetch("ma_cases_view.json")).json();
  const codes = new Set(M.names().map(x => x.c));
  const seen = new Set();
  // 금융·부동산·펀드 출자처럼 사업 시너지로 설명이 안 되는 건, 자기 상호로 시작하는 계열 법인은 뺀다
  const FIN = /투자|펀드|조합|부동산|금융|자산운용|캐피탈|저축은행|보험|신탁|임대|SPC|PFV|특수목적/;
  const nn = x => String(x || "").replace(/㈜|\(주\)|주식회사|\(.*?\)|\s|[.,·&\-]/g, "").toUpperCase();
  let cases = view.cases.filter(c => !c.g && !c.f && c.tb && c.tb.replace(/\s/g, "").length >= 4 && codes.has(c.bc) && (c.a || 0) >= 10
      && !["64", "65", "66", "68"].includes(c.ti) && !FIN.test(c.tb) && !(nn(c.b).length >= 2 && nn(c.t).indexOf(nn(c.b).slice(0, 2)) === 0))
    .filter(c => { const k = c.bc + "|" + c.t; if (seen.has(k)) return false; seen.add(k); return true; });
  if (n && cases.length > n) { const step = cases.length / n; cases = Array.from({length: n}, (_, i) => cases[Math.floor(i * step)]); }
  const rows = [];
  for (const c of cases) {
    const ind = (c.tg && c.tg[0]) || c.ti || "";
    const out = {};
    for (const mode of ["text", "ind"]) {
      if (mode === "ind" && !ind) { out[mode] = null; continue; }
      const inp = { products: c.tb.replace(/\s+/g, " "), keywords: "", materials: "", tech: "", issues: "", customers: "", similar: "",
        industries: mode === "ind" ? [{ code: ind, name: M.ksicNameOf(ind) }] : [], custIndustries: [], fin: { price: c.a } };
      const res = M.run(inp, { loo: c.bc, looCase: { r: c.r, t: c.t, bc: c.bc } });
      const i = res.findIndex(x => x.c.c === c.bc);
      out[mode] = i >= 0 ? i + 1 : 9999;
      if (mode === "text") { const L = window.MNA_MATCH_LAST || []; const j = L.findIndex(x => x.c.c === c.bc); out.raw = j >= 0 ? j + 1 : 9999; out.pool = L.length;
        const o = j >= 0 ? L[j] : null; out.sig = o ? { h: +o.s.h.toFixed(3), v: +Math.max(o.s.vb, o.s.vf).toFixed(3), tr: +o.s.tr.toFixed(2), hs: +(o.s.hs||0).toFixed(2), L: o.s.L, cm: +o.s.capm.toFixed(2), sc: +o.score.toFixed(3), top: +L[0].score.toFixed(3) } : null; }
    }
    rows.push({ bc: c.bc, ti: c.ti, b: c.b, t: c.t.split("\n")[0].slice(0, 20), tb: c.tb.replace(/\s+/g, " ").slice(0, 24), a: c.a, text: out.text, ind: out.ind, raw: out.raw, pool: out.pool, sig: out.sig });
  }
  return rows;
}
"""


def summary(ranks):
    ranks = [r for r in ranks if r is not None]
    if not ranks:
        return "-"
    n = len(ranks)
    f = lambda k: sum(1 for r in ranks if r <= k) / n * 100
    med = statistics.median(ranks)
    return f"n={n}  top10 {f(10):.1f}%  top30 {f(30):.1f}%  top100 {f(100):.1f}%  결과에 없음 {sum(1 for r in ranks if r >= 9999) / n * 100:.1f}%  중앙순위 {'없음' if med >= 9999 else int(med)}"


with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page()
    pg.goto(f"http://localhost:{args.port}/match.html")
    pg.wait_for_function("window.MNA_MATCH")
    rows = pg.evaluate(JS, [json.loads(args.tweak), args.n])
    b.close()

print(f"[{args.label or args.tweak}]")
print("  사업 설명만   :", summary([r["text"] for r in rows]))
print("  +업종 선택   :", summary([r["ind"] for r in rows]))
print("  (참고) 점수순 전체:", summary([r["raw"] for r in rows]))
json.dump(rows, open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
