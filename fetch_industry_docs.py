"""업종 M&A 사례 보강 — 공시 원문(document.xml)을 읽는다.
A) 최근 5년 '타법인주식및출자증권취득결정' 공시 전체를 읽어, 발행회사(인수대상)가 대상 업종이거나 대상 회사인 건을 찾는다.
B) 대상 회사들의 최대주주변경·주식양수도·합병·유상증자 관련 공시 원문을 저장한다.
결과: industry_docs.json (캐시: industry_docs_cache.json, 로그: industry_docs_log.txt)
"""
import os, re, io, json, time, zipfile, html as htmllib, threading
from concurrent.futures import ThreadPoolExecutor
import requests

API_KEY = os.environ.get("DART_API_KEY", "")
BASE = "https://opendart.fss.or.kr/api/"
CACHE = "industry_docs_cache.json"
OUT = "industry_docs.json"
LOG = "industry_docs_log.txt"
START = time.time()
BUDGET = 140 * 60
KW = re.compile(r"배전반|자동제어반|수배전|분전반|배전자동화|개폐기|전력제어")
EV = re.compile(r"최대주주\s*변경|주식양수도|합병결정|영업양수|영업양도|유상증자결정|유상증자결과|증권발행결과|제3자배정|경영권|주식교환|주식매매")
_lock = threading.Lock()
_logs = []
errors = 0


def log(m):
    print(m, flush=True)
    _logs.append(str(m))


def norm(s):
    return re.sub(r"\(주\)|㈜|주식회사|\s", "", s or "")


def doc_text(rno):
    global errors
    for i in range(3):
        try:
            r = requests.get(BASE + "document.xml", params={"crtfc_key": API_KEY, "rcept_no": rno}, timeout=40)
            raw = r.content
            break
        except requests.RequestException:
            time.sleep(1.5 * (i + 1))
    else:
        return None
    if raw[:5] == b"<?xml":
        errors += 1
        if errors <= 3:
            log("원문 오류: " + raw[:200].decode("utf-8", "replace"))
        return None
    try:
        z = zipfile.ZipFile(io.BytesIO(raw))
        data = z.read(z.namelist()[0])
    except Exception:
        return None
    for enc in ("utf-8", "euc-kr", "cp949"):
        try:
            t = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        return None
    t = re.sub(r"<[^>]+>", "\n", t)
    t = htmllib.unescape(t).replace("\xa0", " ")
    toks = [x.strip() for x in t.split("\n") if x.strip()]
    toks = [x for x in toks if not re.search(r"[{};]|^\.|font-|padding|border|color:", x)]
    return " | ".join(toks)


def main():
    ind = json.load(open("industry_deals.json", encoding="utf-8"))
    names = {norm(c["name"]): c["name"] for c in ind["companies"]}
    ma = json.load(open("ma_cache.json", encoding="utf-8"))["filings"]
    cache = json.load(open(CACHE, encoding="utf-8")) if os.path.exists(CACHE) else {"done": [], "hits": {}, "ev": {}}
    done = set(cache["done"])

    # A) 취득결정 공시 원문 전수
    acq = [f for f in ma.values() if f["kind"] == "acq" and f["rcept_no"] not in done]
    log(f"A) 취득공시 원문 읽기 {len(acq)}건 (이미 완료 {len(done)})")
    cnt = {"n": 0}

    def work_a(f):
        if errors >= 8 or time.time() - START > BUDGET:
            return
        t = doc_text(f["rcept_no"])
        time.sleep(0.05)
        if t is None:
            return
        low = norm(t)
        hit_kw = bool(KW.search(t))
        hit_nm = [n for k, n in names.items() if k and k in low and k != norm(f["corp_name"])]
        with _lock:
            done.add(f["rcept_no"])
            if hit_kw or hit_nm:
                i = t.find("회사명")
                cache["hits"][f["rcept_no"]] = {"corp": f["corp_name"], "date": f["date"], "name_hit": hit_nm,
                                                "kw": hit_kw, "text": t[:6000]}
            cnt["n"] += 1
            if cnt["n"] % 300 == 0:
                cache["done"] = sorted(done)
                json.dump(cache, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
                log(f"  진행 {cnt['n']}건, 후보 {len(cache['hits'])}건")

    with ThreadPoolExecutor(max_workers=4) as ex:
        list(ex.map(work_a, acq))
    cache["done"] = sorted(done)

    # B) 대상 회사 주요 공시 원문
    todo = []
    for name, fl in ind["filings"].items():
        for f in fl:
            if EV.search(f["report_nm"]) and "변동신고서" not in f["report_nm"] and f["rcept_no"] not in cache["ev"]:
                todo.append((name, f))
    log(f"B) 대상 회사 공시 원문 {len(todo)}건")

    def work_b(x):
        name, f = x
        if errors >= 8 or time.time() - START > BUDGET:
            return
        t = doc_text(f["rcept_no"])
        time.sleep(0.05)
        if t is None:
            return
        with _lock:
            cache["ev"][f["rcept_no"]] = {"company": name, "date": f["date"], "report_nm": re.sub(r"\s+", " ", f["report_nm"]),
                                          "text": t[:4500]}

    with ThreadPoolExecutor(max_workers=4) as ex:
        list(ex.map(work_b, todo))

    json.dump(cache, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    json.dump({"acq_hits": sorted(cache["hits"].items()), "events": sorted(cache["ev"].items())},
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    log(f"완료: 취득 후보 {len(cache['hits'])}건, 이벤트 원문 {len(cache['ev'])}건, 원문 오류 {errors}")


if __name__ == "__main__":
    try:
        main()
    finally:
        open(LOG, "w", encoding="utf-8").write("\n".join(_logs))
