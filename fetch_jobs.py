"""금융투자협회 회원사 채용안내(kofia.or.kr/brd/m_96) 최근 30일 공고 제목·링크 수집."""
import re
import json
import time
import datetime as dt

import requests
from bs4 import BeautifulSoup

BASE = "https://www.kofia.or.kr/brd/m_96/"
OUT = "jobs.json"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
DAYS = 30
MAX_PAGES = 15


def parse(html):
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for tr in soup.select("tbody tr"):
        tds = tr.find_all("td")
        if len(tds) < 4:
            continue
        txt = [re.sub(r"\s+", " ", td.get_text(" ", strip=True)) for td in tds]
        date = next((t for t in reversed(txt) if re.fullmatch(r"\d{4}[-./]\d{2}[-./]\d{2}", t)), None)
        if date:
            date = re.sub(r"[./]", "-", date)
        seq = None
        title = ""
        for a in tr.find_all("a", href=True):
            m = re.search(r"seq=(\d+)", a["href"])
            if m:
                seq = m.group(1)
                td = a.find_parent("td")
                t = (td or a).get_text(" ", strip=True)
                if len(t) > len(title):
                    title = re.sub(r"\s+", " ", t)
        if not (date and seq and title):
            continue
        company = txt[1] if len(txt) > 1 else ""
        rows.append({"company": company, "title": title, "date": date,
                     "link": BASE + "view.do?seq=" + seq})
    return rows


def main():
    cutoff = (dt.datetime.utcnow() + dt.timedelta(hours=9) - dt.timedelta(days=DAYS)).strftime("%Y-%m-%d")
    out, stop = [], False
    for page in range(1, MAX_PAGES + 1):
        try:
            r = requests.get(BASE + "list.do", params={"page": page}, headers=UA, timeout=20)
            r.raise_for_status()
        except Exception as e:
            print("채용안내 조회 실패:", page, e)
            break
        rows = parse(r.text)
        if not rows:
            break
        for x in rows:
            if x["date"] < cutoff:
                stop = True
            else:
                out.append(x)
        if stop:
            break
        time.sleep(0.5)
    if out:   # 실패 시 기존 파일 유지
        with open(OUT, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"금융투자협회 채용공고 {len(out)}건 (최근 {DAYS}일)")


if __name__ == "__main__":
    main()
