"""화장품 용기·유리병 관련 상장사 전수 확인 → pkg_scan.json (저장소 main 에는 올리지 않음)

- 대상: 상장사 전체 (DART 고유번호 목록 기준)
- 자료: 2026년에 제출된 가장 최근 정기보고서(사업/반기/분기) 본문
- 뽑는 것
  1) 'II. 사업의 내용 → 원재료' 표에서 용기·유리병·부자재·포장재 행 (= 용기를 사 쓰는 회사)
  2) 'II. 사업의 내용' 전체 문장 중 화장품 용기·유리병·초자·패키징 언급 (= 용기를 만들거나 다루는 회사)
  3) 같은 부분의 인수·M&A·사업다각화 언급 문장 (인수 의향 신호)
  4) '화장품' 단어 등장 횟수 (화장품 관련도)
"""
import io
import os
import re
import json
import time
import zipfile
import threading
from html import unescape
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import requests

from fetch_peers import load_corp_map

API_KEY = os.environ.get("DART_API_KEY", "")
BASE = "https://opendart.fss.or.kr/api/"
OUT = "pkg_scan.json"
WORKERS = 5
BUDGET = 150 * 60

RAW = re.compile(r"용기|유리병|공병|초자|부자재|포장재|패키지|패키징|튜브|스포이드|펌프|캡|병마개|향수병|글라스|bottle|container|packag|jar", re.I)
RAW_NOT = re.compile(r"압력\s?용기|고압\s?용기|반응\s?용기|저장\s?용기|가스\s?용기|수소\s?용기|CNG|LPG|컨테이너선|해상\s?컨테이너|캡슐|캡티브|캡처|펌프카|진공\s?펌프|히트\s?펌프|산업용\s?펌프|오일\s?펌프|워터\s?펌프|연료\s?펌프|반도체\s?패키지|패키지\s?기판|PKG\s?기판|BGA|FC-?BGA|SiP|커버\s?글라스|글라스\s?기판|Glass\s?기판", re.I)
BIZ = re.compile(r"화장품\s?용기|화장품\s?(패키지|패키징|포장)|코스메틱\s?(패키지|패키징)|유리\s?용기|유리병|병\s?유리|초자|향수\s?병|제병|프리\s?몰드|화장품\s?부자재|용기\s?(제조|사업|부문|생산)|포장\s?용기|펌프\s?용기|에어리스|스포이드|디퓨저", re.I)
MA = re.compile(r"인수\s?합병|M\s?&\s?A|지분\s?인수|기업\s?인수|인수를\s?(검토|추진|통해)|볼트\s?온|사업\s?다각화|수직\s?계열화|밸류\s?체인")


_lock = threading.Lock()
status = Counter()
hits = []


def get(url, params, binary=False):
    for a in range(4):
        try:
            r = requests.get(url, params=params, timeout=60)
            if binary:
                if r.content[:2] == b"PK":
                    return r.content
                try:
                    j = r.json()
                    if j.get("status") == "020":
                        time.sleep(5 * (a + 1)); continue
                    return None
                except Exception:
                    return None
            j = r.json()
            if j.get("status") == "020":
                time.sleep(5 * (a + 1)); continue
            return j
        except Exception:
            time.sleep(2 + a)
    return None


def latest_report(corp):
    j = get(BASE + "list.json", {"crtfc_key": API_KEY, "corp_code": corp, "bgn_de": "20260101", "end_de": "20261231",
                                 "pblntf_ty": "A", "page_count": 100})
    if not j or j.get("status") != "000":
        return None
    rows = [x for x in j.get("list") or [] if re.search(r"사업보고서|반기보고서|분기보고서", x.get("report_nm", "")) and "첨부" not in x.get("report_nm", "")]
    rows.sort(key=lambda x: x["rcept_dt"], reverse=True)
    return rows[0] if rows else None


def doc_text(rcept):
    b = get(BASE + "document.xml", {"crtfc_key": API_KEY, "rcept_no": rcept}, binary=True)
    if not b:
        return None
    z = zipfile.ZipFile(io.BytesIO(b))
    names = sorted(z.namelist(), key=lambda n: -z.getinfo(n).file_size)
    raw = z.read(names[0])
    for enc in ("utf-8", "euc-kr", "cp949"):
        try:
            return raw.decode(enc)
        except Exception:
            pass
    return raw.decode("utf-8", "ignore")


def clean(s):
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", unescape(s)).strip()


def sections(xml):
    """('사업의 내용' 전체, '원재료' 부분) 원문 XML"""
    titles = [(m.start(), clean(m.group(1))) for m in re.finditer(r"<TITLE[^>]*>(.*?)</TITLE>", xml, re.S | re.I)]
    biz = raw = ""
    for i, (pos, t) in enumerate(titles):
        if not biz and "사업의 내용" in t:
            end = len(xml)
            for pos2, t2 in titles[i + 1:]:
                if re.match(r"^\s*III\s*\.|^\s*Ⅲ|재무에 관한", t2):
                    end = pos2; break
            biz = xml[pos:end]
        if not raw and "원재료" in t:
            end = titles[i + 1][0] if i + 1 < len(titles) else len(xml)
            raw = xml[pos:end]
    if not raw:
        k = xml.find("주요 원재료")
        raw = xml[k:k + 60000] if k >= 0 else ""
    return biz, raw


def tables(sec):
    out = []
    for tm in re.finditer(r"<TABLE[^>]*>(.*?)</TABLE>", sec, re.S | re.I):
        start = tm.start()
        before = clean(sec[max(0, start - 400):start])
        unit = re.findall(r"\(?단위\s*[:：]\s*([^)\]]+)", before + " " + clean(tm.group(1))[:200])
        rows = []
        for rm in re.finditer(r"<TR[^>]*>(.*?)</TR>", tm.group(1), re.S | re.I):
            cells = [clean(c) for c in re.findall(r"<(?:TD|TE|TH|TU)[^>]*>(.*?)</(?:TD|TE|TH|TU)>", rm.group(1), re.S | re.I)]
            if any(cells):
                rows.append(cells)
        out.append({"unit": unit[-1].strip() if unit else "", "rows": rows})
    return out


def sentences(text):
    return [s.strip() for s in re.split(r"(?<=[다요음함])\.\s+|(?<=\.)\s+(?=[가-힣A-Z(\[①-⑳□■○●▶-])|\s[□■○●▶◆◇-]\s", text) if 8 <= len(s.strip()) <= 400]


def work(item):
    stock, corp, name, ic, mkt = item
    rep = latest_report(corp)
    if not rep:
        with _lock:
            status["보고서 없음"] += 1
        return
    xml = doc_text(rep["rcept_no"])
    if not xml:
        with _lock:
            status["본문 없음"] += 1
        return
    biz, raw = sections(xml)
    raw_rows = []
    for t in tables(raw):
        if not t["rows"]:
            continue
        head = t["rows"][0]
        for r in t["rows"][1:]:
            txt = " | ".join(r)
            if RAW.search(txt) and not RAW_NOT.search(txt):
                raw_rows.append({"head": head, "row": r, "unit": t["unit"]})
    text = clean(biz) if biz else ""
    sents = sentences(text)
    biz_s, ma_s, seen = [], [], set()
    for s in sents:
        k = s[:60]
        if k in seen:
            continue
        seen.add(k)
        if BIZ.search(s) and not RAW_NOT.search(s) and len(biz_s) < 8:
            biz_s.append(s)
        if MA.search(s) and len(ma_s) < 4:
            ma_s.append(s)
    cos = text.count("화장품")
    with _lock:
        status["확인"] += 1
        if raw_rows or biz_s or cos >= 3:
            status["관련"] += 1
            hits.append({"stock": stock, "corp": name, "mkt": mkt, "ic": ic, "report": rep["report_nm"], "rcept": rep["rcept_no"],
                         "date": rep["rcept_dt"], "raw": raw_rows[:12], "biz": biz_s, "ma": ma_s, "cos": cos})


def main():
    if not API_KEY:
        print("DART_API_KEY 없음"); return
    idx = {x["c"]: x for x in json.load(open("match_index.json", encoding="utf-8"))["c"]}
    cm = load_corp_map()
    todo = []
    for s, (c, n) in cm.items():
        x = idx.get(s) or {}
        todo.append((s, c, x.get("n") or n, x.get("ic") or "", x.get("m") or ""))
    print("대상", len(todo), flush=True)
    t0 = time.time()
    done = [0]

    def run(a):
        if time.time() - t0 > BUDGET:
            with _lock:
                status["시간 초과로 건너뜀"] += 1
            return
        try:
            work(a)
        except Exception as e:
            with _lock:
                status["오류:" + type(e).__name__] += 1
        with _lock:
            done[0] += 1
            if done[0] % 200 == 0:
                print(f"  {done[0]}/{len(todo)} ({time.time() - t0:.0f}초) {dict(status)}", flush=True)

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        list(ex.map(run, todo))
    hits.sort(key=lambda h: (-len(h["biz"]), -len(h["raw"]), h["corp"]))
    json.dump({"status": dict(status), "n": len(todo), "hits": hits}, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    print("완료", dict(status), f"{time.time() - t0:.0f}초")


if __name__ == "__main__":
    main()
