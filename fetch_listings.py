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


DEBUG_LOG = []


def decode_google_news_link(session, page_html):
    """구글 뉴스의 news.google.com/rss/articles/CBMi... 링크는 실제 URL이 아니라
    자바스크립트 SPA가 내부적으로 풀어내는 난독화된 토큰이다. 기사 페이지의
    <c-wiz data-p="..."> 안에 실제 URL을 얻기 위한 서명값이 들어있어, 구글의
    내부 batchexecute 엔드포인트에 그 서명을 그대로 되돌려 보내면 실제 언론사
    URL을 알려준다. (공개적으로 알려진 우회 방법)"""
    soup = BeautifulSoup(page_html, "html.parser")
    c_wiz = soup.select_one("c-wiz[data-p]")
    if not c_wiz:
        return None
    data_p = c_wiz.get("data-p")
    obj = json.loads(data_p.replace("%.@.", '["garturlreq",'))
    payload = {
        "f.req": json.dumps([[["Fbv4je", json.dumps(obj[:-6] + obj[-2:]), "null", "generic"]]])
    }
    headers = {**UA, "content-type": "application/x-www-form-urlencoded;charset=UTF-8"}
    r2 = session.post(
        "https://news.google.com/_/DotsSplashUi/data/batchexecute",
        headers=headers, data=payload, timeout=15,
    )
    r2.raise_for_status()
    array_string = json.loads(r2.text.split("\n\n", 1)[1])[0][2]
    return json.loads(array_string)[1]


def resolve_real_url(google_link, domain_hint):
    """구글 뉴스 RSS의 링크는 news.google.com으로 감싸진 리다이렉트/난독화 링크라
    실제 언론사 URL을 별도로 찾아내야 한다."""
    try:
        with requests.Session() as session:
            session.headers.update(UA)
            r = session.get(google_link, timeout=15)
            info = {"link": google_link, "status": r.status_code, "final_url": r.url}
            if domain_hint in r.url:
                info["result"] = "redirected"
                DEBUG_LOG.append(info)
                return r.url  # 이미 실제 언론사 URL로 리다이렉트된 경우
            # 본문에 실제 URL이 그대로 노출돼 있는 경우 (가끔 있음)
            m = re.search(r'https?://(?:www\.)?' + re.escape(domain_hint) + r'/[^"\'\\<>\s]+', r.text)
            if m:
                info["result"] = "regex_found"
                DEBUG_LOG.append(info)
                return m.group(0)
            # 최후 수단: 구글 내부 API로 실제 URL 디코딩 시도
            try:
                real = decode_google_news_link(session, r.text)
                info["result"] = "decoded" if real else "decode_failed"
                info["decoded_url"] = real
                DEBUG_LOG.append(info)
                return real
            except Exception as e:
                info["result"] = "decode_error"
                info["error"] = str(e)
                DEBUG_LOG.append(info)
                return None
    except Exception as e:
        DEBUG_LOG.append({"link": google_link, "error": str(e)})
        return None


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

        clean_title = re.sub(r"\s*-\s*[^-]+$", "", it["title"]).strip()  # " - 매일경제 마켓" 등 언론사 접미사 제거
        # 같은 기사가 구글 뉴스에 다른 섹션(예: "매일경제"/"매일경제 마켓"/모바일 URL)으로
        # 중복 노출되는 경우가 있어, 제목 기준으로 먼저 중복 제거한다 (URL은 같은 기사라도
        # 섹션마다 달라질 수 있어 신뢰할 수 없음).
        article_key = ("매일경제", clean_title)
        if article_key in existing_keys:
            continue

        real_link = resolve_real_url(it["link"], "mk.co.kr")
        canonical_link = real_link or it["link"]

        sell_rows, buy_rows = [], []
        if real_link:
            try:
                r = requests.get(real_link, headers=UA, timeout=20)
                r.raise_for_status()
                sell_rows, buy_rows = parse_mk_tables(r.text)
                DEBUG_LOG.append({
                    "stage": "mk_body", "link": real_link, "status": r.status_code,
                    "len": len(r.text), "has_keyword": "매물 기업정보" in r.text,
                    "table_count": r.text.count("<table"),
                    "sell_rows": len(sell_rows), "buy_rows": len(buy_rows),
                })
            except Exception as e:
                print(f"매일경제 본문 조회 실패 [{real_link}]: {e}")
                DEBUG_LOG.append({"stage": "mk_body", "link": real_link, "error": str(e)})
        else:
            print(f"매일경제 실제 기사 URL을 찾지 못함 (구글 리다이렉트만 있음): {it['title']}")

        base = {
            "outlet": "매일경제",
            "article_title": clean_title,
            "article_link": canonical_link,
            "pubDate": it["pubDate"],
        }
        if not sell_rows and not buy_rows:
            # 표 파싱에 실패해도 기사 자체는 놓치지 않도록 제목만으로 매물 1건 등록
            items_out.append({**base, "type": "sell", "industry": "", "revenue": "", "feature": clean_title})
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


def add_hankyung_item(link, title, pub_dt_str, existing_keys, items_out, added):
    tm = HK_TITLE_RE.search(title)
    if not tm:
        # "매출 OOO억 OOO 매물로" 패턴이 아니면 M&A 매물 코너 기사가 아닐 가능성이 커서
        # (예: 부동산 매물 기사) 제외한다.
        return
    article_key = ("한국경제", title)  # URL보다 제목이 더 안정적인 중복 판단 기준
    if article_key in existing_keys:
        return
    revenue, feature = tm.group(1), tm.group(2)
    items_out.append({
        "outlet": "한국경제", "article_title": title, "article_link": link,
        "pubDate": pub_dt_str,
        "type": "sell", "label": "", "industry": "", "revenue": revenue, "feature": feature,
    })
    existing_keys.add(article_key)
    added[0] += 1


def collect_hankyung(existing_keys, added, items_out):
    # 1) 연재 태그 페이지에서 직접 수집 (가장 정확하지만, 목록이 자바스크립트로
    #    렌더링되는 경우 못 잡을 수 있어 아래 2)로 보완한다)
    try:
        r = requests.get(HK_TAG_URL, headers=UA, timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
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
            pub_str = pub_dt.strftime("%a, %d %b %Y 00:00:00 GMT") if pub_dt else ""
            add_hankyung_item(link, title, pub_str, existing_keys, items_out, added)
    except Exception as e:
        print(f"한국경제 연재 태그 페이지 조회 실패: {e}")

    # 2) 구글 뉴스 검색으로 보완 수집 (태그 페이지가 자바스크립트 렌더링이거나
    #    구조가 바뀌어도 놓치지 않도록 하는 백업 경로)
    try:
        found = fetch_rss('"매물로" 억 site:hankyung.com')
    except Exception as e:
        print(f"한국경제 구글 뉴스 검색 실패: {e}")
        found = []
    for it in found:
        if "매물로" not in it["title"]:
            continue
        pub_dt = parse_rss_pub(it["pubDate"])
        if pub_dt is not None and pub_dt < START_DATE:
            continue
        real_link = resolve_real_url(it["link"], "hankyung.com")
        if not real_link:
            continue
        clean_title = re.sub(r"\s*\|\s*한국경제\s*$", "", it["title"]).strip()
        add_hankyung_item(real_link, clean_title, it["pubDate"], existing_keys, items_out, added)


def main():
    existing = []
    if os.path.exists(OUT):
        with open(OUT, encoding="utf-8") as f:
            existing = json.load(f)
    # 매물/인수 행 여러 개가 기사 하나에서 나올 수 있어, 중복 판단은 (매체, 기사 제목) 기준으로 한다.
    existing_keys = {(e.get("outlet"), e.get("article_title")) for e in existing}
    added = [0]
    items_out = []

    collect_mk(existing_keys, added, items_out)
    collect_hankyung(existing_keys, added, items_out)

    with open("_debug_listings.json", "w", encoding="utf-8") as f:
        json.dump(DEBUG_LOG, f, ensure_ascii=False, indent=1)

    existing.extend(items_out)
    existing.sort(key=lambda e: e.get("pubDate", ""), reverse=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=1)
    print(f"매물·인수희망 리스트 신규 {added[0]}건 추가, 전체 {len(existing)}건")


if __name__ == "__main__":
    main()
