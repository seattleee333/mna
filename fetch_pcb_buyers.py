"""PCB(기판·보드) 매입 상장사 찾기 → pcb_buyers.json (작업 결과물로만 내려받고 저장소에는 올리지 않음)

- 대상: 제조업·IT 등 업종의 상장사 (match_index.json 의 업종코드 기준)
- 자료: 2026년에 제출된 가장 최근 정기보고서(사업/반기/분기) 본문의 'II. 사업의 내용 → 원재료' 부분
- 원재료 표에서 PCB·PBA·FPCB·기판·보드(Board)가 들어간 행을 그대로 뽑는다 (품목·용도·매입액·비중·매입처 등 표에 있는 그대로)
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
OUT = "pcb_buyers.json"
WORKERS = 5
BUDGET = 150 * 60
KEEP = {str(i) for i in range(20, 35)} | {"46", "58", "61", "62", "63", "70", "71", "72", "73", "75", "95"}
PCB = re.compile(r"P\.?C\.?B|PBA|FPCB|PCBA|MLB|HDI|기판|보드|board", re.I)
NOT_PCB = re.compile(r"키보드|대시보드|스노우보드|보드게임|화이트보드|석고보드|하드보드|파티클보드|섬유판|MDF|보드지|판지|골판|게시판|대시|블랙보드|합판|코르크", re.I)
TAG = re.compile(r"<(TITLE|TABLE|/TABLE|TR|/TR|TD|/TD|TE|/TE|TH|/TH|TU|/TU|P|/P|SPAN|/SPAN)[^>]*>", re.I)

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


def raw_section(xml):
    """'원재료' 제목부터 다음 제목까지 (없으면 '주요 원재료' 문구 주변)"""
    titles = [m for m in re.finditer(r"<TITLE[^>]*>(.*?)</TITLE>", xml, re.S | re.I)]
    for i, m in enumerate(titles):
        if "원재료" in clean(m.group(1)):
            end = titles[i + 1].start() if i + 1 < len(titles) else len(xml)
            return xml[m.start():end]
    k = xml.find("주요 원재료")
    return xml[k:k + 60000] if k >= 0 else ""


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
        out.append({"unit": unit[-1].strip() if unit else "", "rows": rows, "before": before[-120:]})
    return out


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
    sec = raw_section(xml)
    if not sec:
        with _lock:
            status["원재료 항목 없음"] += 1
        return
    found = []
    for t in tables(sec):
        if not t["rows"]:
            continue
        head = t["rows"][0]
        for r in t["rows"][1:]:
            txt = " | ".join(r)
            if PCB.search(txt) and not NOT_PCB.search(txt):
                found.append({"head": head, "row": r, "unit": t["unit"]})
    # 표 밖 문장에서만 언급된 경우도 남긴다
    text = clean(sec)
    mention = ""
    if not found:
        m = PCB.search(text)
        if m and not NOT_PCB.search(text[max(0, m.start() - 15):m.end() + 15]):
            mention = text[max(0, m.start() - 120):m.end() + 160]
    with _lock:
        status["확인"] += 1
        if found or mention:
            status["PCB 언급"] += 1
            hits.append({"stock": stock, "corp": name, "mkt": mkt, "ic": ic, "report": rep["report_nm"], "rcept": rep["rcept_no"],
                         "date": rep["rcept_dt"], "rows": found, "mention": mention})


def main():
    if not API_KEY:
        print("DART_API_KEY 없음"); return
    idx = {x["c"]: x for x in json.load(open("match_index.json", encoding="utf-8"))["c"]}
    cm = load_corp_map()
    todo = []
    for s, (c, n) in cm.items():
        x = idx.get(s)
        if x and (x.get("ic") or "")[:2] in KEEP:
            todo.append((s, c, x.get("n") or n, x.get("ic"), x.get("m")))
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
    hits.sort(key=lambda h: (h["mkt"] or "", h["corp"]))
    json.dump({"status": dict(status), "n": len(todo), "hits": hits}, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    print("완료", dict(status), f"{time.time() - t0:.0f}초")


if __name__ == "__main__":
    main()
