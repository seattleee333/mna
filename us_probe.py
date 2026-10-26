"""임시 점검: SEC 전문검색(efts)으로 올해 8-K 'Item 2.01' 건을 한 번에 모을 수 있는지 확인"""
import os, json, requests, time
UA = os.environ.get("SEC_USER_AGENT") or "ALL-ABOUT-MNA/1.0 (https://github.com/seattleee333/mna)"
H = {"User-Agent": UA, "Accept-Encoding": "gzip, deflate"}
out = []
def log(m): print(m, flush=True); out.append(str(m))
def q(params):
    r = requests.get("https://efts.sec.gov/LATEST/search-index", params=params, headers=H, timeout=40)
    log(f"HTTP {r.status_code} {r.url[:200]}")
    if r.status_code != 200:
        log(r.text[:300]); return None
    return r.json()
for qq in ['"Completion of Acquisition or Disposition of Assets"', '"Item 2.01"']:
    d = q({"q": qq, "forms": "8-K", "dateRange": "custom", "startdt": "2026-01-01", "enddt": "2026-01-31"})
    if not d: continue
    h = d.get("hits", {})
    log(f"query={qq} total={h.get('total')}")
    for x in h.get("hits", [])[:3]:
        s = x.get("_source", {})
        log(json.dumps({k: s.get(k) for k in s if k in ("display_names","file_date","items","form","adsh","ciks","root_forms","file_type")}, ensure_ascii=False)[:400])
    log("keys: " + ",".join(sorted((h.get("hits") or [{}])[0].get("_source", {}).keys())))
    time.sleep(0.5)
    d2 = q({"q": qq, "forms": "8-K", "dateRange": "custom", "startdt": "2026-01-01", "enddt": "2026-01-31", "from": 100})
    if d2: log(f"page2 hits={len(d2.get('hits',{}).get('hits',[]))}")
open("us_probe.txt", "w", encoding="utf-8").write("\n".join(out))
