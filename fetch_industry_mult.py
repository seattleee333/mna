"""배전반 업종 상장사 13곳의 PER·EV/EBITDA·PBR (최근 사업연도 재무 + 현재 시가총액) 및 딜 사례용 연도별 재무.
결과: industry_mult.json (로그: industry_mult_log.txt)
"""
import json, time, datetime as dt
import fetch_peers as fp

LOG = []
def log(m):
    print(m, flush=True); LOG.append(str(m))

def main():
    ind = json.load(open("industry_deals.json", encoding="utf-8"))
    corp_map = fp.load_corp_map()
    by_corp = {v[0]: k for k, v in corp_map.items()}
    out = {"updated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "companies": []}
    now_year = dt.date.today().year
    for c in sorted(ind["companies"], key=lambda c: c["name"]):
        code = c["stock"] or by_corp.get(c["corp_code"])
        rec = {"name": c["name"], "code": code, "corp_code": c["corp_code"], "years": {}}
        mcap, src = fp.fetch_mcap(code) if code else (None, None)
        rec["mcap"], rec["mcap_src"] = mcap, src
        for y in range(now_year - 4, now_year):
            rows, fs = fp.fetch_fin(c["corp_code"], y)
            if not rows:
                continue
            mt = fp.extract_metrics(rows)
            if mt["da"] is None:
                xda, why = fp.da_from_xbrl(c["corp_code"], y, fs)
                if xda is not None:
                    mt["da"] = xda; mt["da_src"] = "xbrl"
                else:
                    mt["da_why"] = why
            # 자본총계(지배)·자산·매출
            def pick(names, sj=None):
                for r in rows:
                    nm = fp.norm_nm(r.get("account_nm"))
                    if nm in names and (sj is None or r.get("sj_div") in sj):
                        v = fp.parse_amt(r.get("thstrm_amount"))
                        if v is not None:
                            return v
            mt["rev"] = pick({"매출액", "수익(매출액)", "영업수익"}, ("IS", "CIS"))
            mt["equity"] = pick({"자본총계"}, ("BS",))
            mt["equity_own"] = pick({"지배기업소유주지분", "지배기업의소유주에게귀속되는자본"}, ("BS",)) or mt["equity"]
            mt["fs"] = fs
            rec["years"][str(y)] = mt
            log(f"{c['name']} {y} {fs} op={mt['op']} da={mt['da']} ni={mt['ni']}")
            time.sleep(0.2)
        out["companies"].append(rec)
    json.dump(out, open("industry_mult.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)

if __name__ == "__main__":
    try:
        main()
    finally:
        open("industry_mult_log.txt", "w", encoding="utf-8").write("\n".join(LOG))
