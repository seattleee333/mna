"""M&A 관련 직접채용 공고 수집 (최근 30일).
- 금융투자협회 회원사 채용안내(kofia.or.kr/brd/m_96): 제목에 M&A·IB 관련 키워드가 있는 공고만
- 사람인 공식 Open API(SARAMIN_API_KEY가 있을 때만): 키워드 검색, 헤드헌팅·파견 업체 제외
"""
import re
import json
import time
import datetime as dt

import os
import requests
from bs4 import BeautifulSoup

BASE = "https://www.kofia.or.kr/brd/m_96/"
OUT = "jobs.json"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
DAYS = 30
MAX_PAGES = 80
MA_RE = re.compile(r"M\s*&\s*A|엠앤에이|인수\s*·?\s*합병|인수합병|기업금융|투자금융|투자은행|인수금융|구조화금융|사모투자|프라이빗\s*에쿼티|(?<![A-Za-z])(IB|PEF?|ECM|DCM)(?![A-Za-z])", re.I)
HEADHUNT_RE = re.compile(r"헤드\s*헌팅|서치|써치|리크루팅|리쿠르|인력|파견|아웃소싱|HR|커리어|인재|Search|Recruit", re.I)


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


def fetch_saramin(cutoff):
    key = os.environ.get("SARAMIN_API_KEY", "")
    if not key:
        print("SARAMIN_API_KEY 없음 - 사람인 건너뜀")
        return []
    res = []
    for kw in ("M&A", "인수합병", "인수금융", "기업금융 IB"):
        try:
            r = requests.get("https://oapi.saramin.co.kr/job-search",
                             params={"access-key": key, "keywords": kw, "count": 110, "sort": "pd"},
                             headers={"Accept": "application/json"}, timeout=20)
            jobs = r.json().get("jobs", {}).get("job", [])
        except Exception as e:
            print("사람인 조회 실패:", kw, e)
            continue
        for j in jobs:
            try:
                comp = j["company"]["detail"]["name"]
                title = j["position"]["title"]
                date = dt.datetime.fromtimestamp(int(j["posting-timestamp"]), dt.timezone(dt.timedelta(hours=9))).strftime("%Y-%m-%d")
            except Exception:
                continue
            if date < cutoff or HEADHUNT_RE.search(comp) or not MA_RE.search(title + " " + (j.get("position", {}).get("industry", {}).get("name", ""))):
                continue
            res.append({"company": comp, "title": title, "date": date, "link": j.get("url", ""), "source": "사람인"})
    seen, uniq = set(), []
    for x in res:
        if x["link"] not in seen:
            seen.add(x["link"]); uniq.append(x)
    print(f"사람인 M&A 직접채용 {len(uniq)}건")
    return uniq


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
            elif MA_RE.search(x["title"]):
                x["source"] = "금융투자협회"
                out.append(x)
        if stop:
            break
        time.sleep(0.5)
    out += fetch_saramin(cutoff)
    out.sort(key=lambda x: x["date"], reverse=True)
    if out:   # 실패 시 기존 파일 유지
        with open(OUT, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"M&A 채용공고 {len(out)}건 (최근 {DAYS}일)")


if __name__ == "__main__":
    main()
