import os
import re
import json
import datetime as dt
import xml.etree.ElementTree as ET
from urllib.parse import quote

import requests

OUT = "listings.json"
START_DATE = dt.datetime(2026, 9, 1)  # 이 날짜 이후 기사만 수집

# 매체명 -> 도메인 (구글 뉴스의 site: 검색으로 매체를 한정)
OUTLETS = {
    "한국경제": "hankyung.com",
    "매일경제": "mk.co.kr",
    "머니투데이": "mt.co.kr",
}

# "매물로 나왔다" / "인수 후보를 찾는다" 류의 기사를 잡기 위한 키워드.
# 구글 뉴스가 단어를 따로따로 느슨하게 매칭하지 않도록 정확한 문구로 감싼다(따옴표).
KEYWORDS = [
    "매각 추진",
    "매물로 나왔다",
    "인수 후보",
    "인수 검토",
    "지분 매각 추진",
    "인수처 물색",
]

# 매일경제 [M&A 매물장터], 한국경제 M&A 장터 처럼 매체가 격주로 연재하는
# 매물 소개 코너를 따로, 더 정확하게 잡기 위한 전용 검색어.
SERIES_QUERIES = {
    "매일경제": ['"M&A 매물장터"'],
    "한국경제": ['"매물로" 억 site:hankyung.com'],  # 한경 코너는 별도 태그 없이 "매출 OOO억 OOO 매물로" 형식의 제목을 씀
}


def fetch(q):
    url = f"https://news.google.com/rss/search?q={quote(q)}&hl=ko&gl=KR&ceid=KR:ko"
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    items = []
    for it in root.findall(".//item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        desc = (it.findtext("description") or "").strip()
        desc = re.sub(r"<[^>]+>", "", desc)  # HTML 태그 제거
        pub = (it.findtext("pubDate") or "").strip()
        if title and link:
            items.append({"title": title, "link": link, "snippet": desc[:200], "pubDate": pub})
    return items


def parse_pub(pub):
    try:
        # 예: "Tue, 29 Sep 2026 01:00:00 GMT"
        return dt.datetime.strptime(pub.split(",", 1)[1].strip().rsplit(" ", 1)[0], "%d %b %Y %H:%M:%S")
    except Exception:
        return None


def add_results(existing, seen_links, outlet, found, tag, added_counter):
    for it in found:
        if it["link"] in seen_links:
            continue
        pub_dt = parse_pub(it["pubDate"])
        if pub_dt is not None and pub_dt < START_DATE:
            continue  # 2026년 9월 이전 기사는 제외
        existing.append({
            "title": it["title"],
            "link": it["link"],
            "snippet": it["snippet"],
            "outlet": outlet,
            "pubDate": it["pubDate"],
            "series": tag,
        })
        seen_links.add(it["link"])
        added_counter[0] += 1


def main():
    existing = []
    if os.path.exists(OUT):
        with open(OUT, encoding="utf-8") as f:
            existing = json.load(f)
    seen_links = {e["link"] for e in existing}
    added = [0]

    # 1) 매체별 격주 연재 매물 코너 (정확도 높은 전용 검색)
    for outlet, queries in SERIES_QUERIES.items():
        for q in queries:
            try:
                found = fetch(q)
            except Exception as e:
                print(f"연재 코너 조회 실패 [{outlet}]: {e}")
                continue
            add_results(existing, seen_links, outlet, found, "매물장터", added)

    # 2) 일반 키워드 기반 매각/인수 희망 기사 (문구를 따옴표로 감싸 정확도를 높임)
    for outlet, domain in OUTLETS.items():
        for kw in KEYWORDS:
            q = f'"{kw}" site:{domain}'
            try:
                found = fetch(q)
            except Exception as e:
                print(f"목록 조회 실패 [{outlet}/{kw}]: {e}")
                continue
            add_results(existing, seen_links, outlet, found, None, added)

    existing.sort(key=lambda e: e.get("pubDate", ""), reverse=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=1)
    print(f"매물·인수희망 리스트 신규 {added[0]}건 추가, 전체 {len(existing)}건")


if __name__ == "__main__":
    main()
