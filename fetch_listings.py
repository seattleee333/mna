import os
import re
import json
import datetime as dt
import xml.etree.ElementTree as ET
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

OUT = "listings.json"
START_DATE = dt.datetime(2026, 9, 1)  # 이 날짜 이후 기사만 수집

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}

# 매일경제 [M&A 매물장터] / 한국경제 M&A 장터 처럼, 매체가 격주로 연재하는
# "익명 매물·인수희망 소개" 코너만 정확히 잡는다. 다른 일반 M&A 뉴스는 수집하지 않는다.


def fetch_rss(q):
    url = f"https://news.google.com/rss/search?q={quote(q)}&hl=ko&gl=KR&ceid=KR:ko"
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    items = []
    for it in root.findall(".//item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        pub = (it.findtext("pubDate") or "").strip()
        if title and link:
            items.append({"title": title, "link": link, "pubDate": pub})
    return items


def parse_rss_pub(pub):
    try:
        # 예: "Tue, 29 Sep 2026 01:00:00 GMT"
        return dt.datetime.strptime(pub.split(",", 1)[1].strip().rsplit(" ", 1)[0], "%d %b %Y %H:%M:%S")
    except Exception:
        return None


# ── 매일경제 [M&A 매물장터]: 한 기사에 매물 여러 건 + 인수희망 여러 건이 표로 묶여 나온다 ──

SELL_HEADER_KEYS = {"구분", "업종", "매출", "특징"}
BUY_HEADER_KEYS = {"구분", "형태", "업종", "인수희망대상", "인수가능금액"}


def parse_mk_tables(html):
    """기사 본문의 <table>에서 '매물 기업정보' / '인수 기업정보' 표를 찾아 행 단위로 구조화한다."""
    soup = BeautifulSoup(html, "html.parser")
    sell_rows, buy_rows = [], []
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue
        headers = [c.get_text(strip=True) for c in rows[0].find_all(["th", "td"])]
        hset = set(headers)
        if BUY_HEADER_KEYS.issubset(hset):
            kind = "buy"
        elif SELL_HEADER_KEYS.issubset(hset):
            kind = "sell"
        else:
            continue
        for tr in rows[1:]:
            cells = [c.get_text(strip=True) for c in tr.find_all(["td", "th"])]
            if len(cells) != len(headers) or not cells[0]:
                continue
            row = dict(zip(headers, cells))
            (buy_rows if kind == "buy" else sell_rows).append(row)
    return sell_rows, buy_rows


def collect_mk(existing_keys, added, items_out):
    try:
        found = fetch_rss('"M&A 매물장터" site:mk.co.kr')
    except Exception as e:
        print(f"매일경제 연재 코너 검색 실패: {e}")
        return
    for it in found:
        if "매물장터" not in it["title"]:
            continue  # 검색이 느슨하게 걸릴 수 있어, 제목에 실제로 코너명이 있는 것만 채택
        pub_dt = parse_rss_pub(it["pubDate"])
        if pub_dt is not None and pub_dt < START_DATE:
            continue
        article_key = ("매일경제", it["link"])
        if article_key in existing_keys:
            continue
        try:
            r = requests.get(it["link"], headers=UA, timeout=20)
            r.raise_for_status()
            sell_rows, buy_rows = parse_mk_tables(r.text)
        except Exception as e:
            print(f"매일경제 본문 조회 실패 [{it['link']}]: {e}")
            sell_rows, buy_rows = [], []

        base = {
            "outlet": "매일경제",
            "article_title": it["title"],
            "article_link": it["link"],
            "pubDate": it["pubDate"],
        }
        if not sell_rows and not buy_rows:
            # 표 파싱에 실패해도 기사 자체는 놓치지 않도록 제목만으로 매물 1건 등록
            items_out.append({**base, "type": "sell", "industry": "", "revenue": "", "feature": it["title"]})
        else:
            for row in sell_rows:
                items_out.append({**base, "type": "sell",
                                   "label": row.get("구분", ""), "industry": row.get("업종", ""),
                                   "revenue": row.get("매출", ""), "feature": row.get("특징", "")})
            for row in buy_rows:
                items_out.append({**base, "type": "buy",
                                   "label": row.get("구분", ""), "form": row.get("형태", ""),
                                   "industry": row.get("업종", ""),
                                   "target_industry": row.get("인수희망대상", ""),
                                   "budget": row.get("인수가능금액", "")})
        existing_keys.add(article_key)
        added[0] += 1


# ── 한국경제 M&A 장터: 기사 하나당 매물 1건, 제목 패턴이 "매출 OOO억 OOO 매물로" ──

HK_TAG_URL = "https://www.hankyung.com/tag/M&A-%EC%9E%A5%ED%84%B0"
HK_TITLE_RE = re.compile(r"매출\s*([\d,]+)\s*억\s*(.+?)\s*매물로")


def collect_hankyung(existing_keys, added, items_out):
    try:
        r = requests.get(HK_TAG_URL, headers=UA, timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        print(f"한국경제 연재 코너 조회 실패: {e}")
        return

    seen_ids = set()
    for a in soup.find_all("a", href=True):
        m = re.search(r"/article/(\d{13,14})", a["href"])
        if not m:
            continue
        art_id = m.group(1)
        if art_id in seen_ids:
            continue
        seen_ids.add(art_id)
        title = a.get_text(strip=True)
        if not title or "매물로" not in title:
            continue
        try:
            pub_dt = dt.datetime.strptime(art_id[:8], "%Y%m%d")
        except ValueError:
            pub_dt = None
        if pub_dt is not None and pub_dt < START_DATE:
            continue
        link = a["href"]
        if link.startswith("/"):
            link = "https://www.hankyung.com" + link
        article_key = ("한국경제", link)
        if article_key in existing_keys:
            continue

        tm = HK_TITLE_RE.search(title)
        revenue, feature = (tm.group(1), tm.group(2)) if tm else ("", title)
        items_out.append({
            "outlet": "한국경제", "article_title": title, "article_link": link,
            "pubDate": pub_dt.strftime("%a, %d %b %Y 00:00:00 GMT") if pub_dt else "",
            "type": "sell", "label": "", "industry": "", "revenue": revenue, "feature": feature,
        })
        existing_keys.add(article_key)
        added[0] += 1


def main():
    existing = []
    if os.path.exists(OUT):
        with open(OUT, encoding="utf-8") as f:
            existing = json.load(f)
    existing_keys = {(e.get("outlet"), e.get("article_link")) for e in existing}
    added = [0]
    items_out = []

    collect_mk(existing_keys, added, items_out)
    collect_hankyung(existing_keys, added, items_out)

    existing.extend(items_out)
    existing.sort(key=lambda e: e.get("pubDate", ""), reverse=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=1)
    print(f"매물·인수희망 리스트 신규 {added[0]}건 추가, 전체 {len(existing)}건")


if __name__ == "__main__":
    main()
