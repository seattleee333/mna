"""1단계: 상장사 추가 DART 수집 (AI 매칭용).
회사별로 4가지를 이어하기 캐시(dart_extra_cache.json)에 저장한다.
  company : 업종코드(induty_code)·결산월·홈페이지·IR주소·전화·대표자·법인구분   (company.json)
  holders : 최대주주 및 5% 이상 주주 현황                                        (hyslrSttus.json)
  invest  : 타법인 출자현황 + 지분 50% 초과 = 종속회사로 표시                    (otrCprInvstmntSttus.json)
  mda     : 'IV. 이사의 경영진단 및 분석의견' 중 M&A·신사업 문장                   (document.xml)
호출량: 회사당 최대 4회 × 약 2,900곳 ≈ 11,600회 (일 한도 20,000 이내). 한도/시간 초과 시 저장 후 종료 → 다시 실행하면 이어서 진행.
환경변수: DART_API_KEY, FY(기본 2025), PILOT=회사명,회사명(일부만 시험), MAX_CALLS(기본 17000)
기존 fetch_profiles.py 의 call/find_reports/doc_xml 을 재사용한다.
"""
import os, re, json, time, threading
from concurrent.futures import ThreadPoolExecutor
import fetch_profiles as fp

FY = fp.FY
PILOT = fp.PILOT
CACHE = "dart_extra_cache.json"
LOG = "dart_extra_log.txt"
BUDGET = int(os.environ.get("BUDGET_MIN", "150")) * 60
MAX_CALLS = int(os.environ.get("MAX_CALLS", "17000"))
START = time.time()
_lock = threading.Lock()
_calls = 0
_stop = False


def log(m):
    fp.log(m)


def api(name, params):
    """호출 수를 세는 DART 호출"""
    global _calls, _stop
    with _lock:
        if _calls >= MAX_CALLS or time.time() - START > BUDGET:
            _stop = True
            return None
        _calls += 1
    d = fp.call(name, params)
    if d.get("status") == "020":          # 일일 한도 초과
        _stop = True
        log("DART 일일 호출 한도 초과(020) — 저장 후 종료")
        return None
    return d


def fnum(v):
    try:
        return float(str(v).replace(",", "").replace("%", "").strip())
    except (ValueError, TypeError):
        return None


def get_company(cc):
    d = api("company.json", {"corp_code": cc})
    if d is None:
        return None
    if d.get("status") != "000":
        return {"err": d.get("status")}
    keys = ["corp_name", "stock_name", "ceo_nm", "corp_cls", "induty_code", "est_dt", "acc_mt", "hm_url", "ir_url", "phn_no", "adres"]
    return {k: (d.get(k) or "").strip() for k in keys}


def get_holders(cc):
    d = api("hyslrSttus.json", {"corp_code": cc, "bsns_year": str(FY), "reprt_code": "11011"})
    if d is None:
        return None
    if d.get("status") != "000":
        return {"err": d.get("status"), "rows": []}
    rows = []
    for r in d.get("list", []):
        if (r.get("stock_knd") or "").strip() not in ("보통주", "의결권 있는 주식", ""):
            continue
        rt = fnum(r.get("trmend_posesn_stock_qota_rt"))
        if rt is None:
            continue
        rows.append({"name": (r.get("nm") or "").strip(), "rel": (r.get("relate") or "").strip(), "rate": rt})
    rows.sort(key=lambda x: -x["rate"])
    return {"rows": rows[:8]}


def get_invest(cc):
    d = api("otrCprInvstmntSttus.json", {"corp_code": cc, "bsns_year": str(FY), "reprt_code": "11011"})
    if d is None:
        return None
    if d.get("status") != "000":
        return {"err": d.get("status"), "rows": []}
    rows = []
    for r in d.get("list", []):
        nm = (r.get("inv_prm") or "").strip()
        if not nm or nm in ("합계", "소계", "계"):
            continue
        rt = fnum(r.get("trmend_blce_qota_rt"))
        rows.append({"name": nm, "purpose": (r.get("invstmnt_purps") or "").strip(), "first": (r.get("frst_acqs_de") or "").strip(),
                     "rate": rt, "book": fnum(r.get("trmend_blce_acntbk_amount")), "sub": bool(rt is not None and rt > 50)})
    return {"rows": rows[:80]}


MDA_KW = re.compile(r"(인수|합병|M&A|지분\s*취득|지분\s*투자|신규\s*사업|신사업|사업\s*다각화|사업\s*확장|진출|전략적\s*투자|지분\s*인수|매각|양수)")


def get_mda(rcept):
    xml = fp.doc_xml(rcept)
    global _calls
    with _lock:
        _calls += 1   # document.xml 도 호출 수에 포함
    if not xml:
        return {"err": "nodoc", "sents": []}
    titles = [(m.start(), m.end(), fp.norm(m.group(1))) for m in re.finditer(r"<TITLE[^>]*>(.*?)</TITLE>", xml, re.S)]
    s = next((i for i, t in enumerate(titles) if re.match(r"^(IV|4)\.?이사의경영진단", t[2])), None)
    if s is None:
        return {"err": "nosec", "sents": []}
    e = next((j for j in range(s + 1, len(titles)) if fp.ROMAN.match(titles[j][2])), None)
    end = titles[e][0] if e is not None else len(xml)
    txt = fp.to_text(xml[titles[s][1]:end])
    sents, seen = [], set()
    for sn in re.split(r"(?<=[.다음])\s+|\n", txt):
        sn = sn.strip()
        if 15 <= len(sn) <= 400 and MDA_KW.search(sn) and sn not in seen:
            seen.add(sn)
            sents.append(sn)
        if len(sents) >= 12:
            break
    return {"sents": sents, "len": len(txt)}


STEPS = [("company", lambda c: get_company(c["corp_code"])),
         ("holders", lambda c: get_holders(c["corp_code"])),
         ("invest", lambda c: get_invest(c["corp_code"])),
         ("mda", lambda c: get_mda(c["rcept_no"]))]


def work(c, cache):
    code = c["code"]
    ent = cache.setdefault(code, {"name": c["name"], "corp_code": c["corp_code"]})
    for key, fn in STEPS:
        if _stop:
            return
        if key in ent:
            continue
        try:
            res = fn(c)
        except Exception as ex:   # 한 회사 실패가 전체를 멈추지 않게
            log(f"{c['name']} {key} 오류: {ex}")
            res = None
        if res is not None:
            ent[key] = res
        time.sleep(0.05)


def main():
    if not fp.API_KEY:
        log("DART_API_KEY 없음"); return
    cache = json.load(open(CACHE, encoding="utf-8")) if os.path.exists(CACHE) else {}
    corps = fp.find_reports()
    log(f"대상 상장사 {len(corps)}곳 (캐시 {len(cache)}곳)")
    todo = [c for c in corps.values() if (not PILOT or c["name"] in PILOT)
            and not all(k in cache.get(c["code"], {}) for k, _ in STEPS)]
    log(f"남은 회사 {len(todo)}곳")
    done = 0
    try:
        with ThreadPoolExecutor(max_workers=4) as ex:
            for _ in ex.map(lambda c: work(c, cache), todo):
                done += 1
                if done % 200 == 0:
                    log(f"  {done}/{len(todo)} 처리, API {_calls}회, {int(time.time() - START)}초")
    finally:
        out = CACHE if not PILOT else "dart_extra_pilot.json"
        data = cache if not PILOT else {c["code"]: cache[c["code"]] for c in corps.values() if c["name"] in PILOT and c["code"] in cache}
        json.dump(data, open(out, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
        full = sum(1 for v in cache.values() if all(k in v for k, _ in STEPS))
        log(f"저장 {out}: 전체 완료 {full}곳 / API {_calls}회 / {'한도·시간 중단' if _stop else '정상 종료'}")
        open(LOG, "w", encoding="utf-8").write("\n".join(fp._logs))


if __name__ == "__main__":
    main()
