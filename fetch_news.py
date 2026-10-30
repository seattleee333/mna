import os
import re
import json
import datetime as dt
import xml.etree.ElementTree as ET
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime
from urllib.parse import quote

import requests

OUT = "news.json"
KEEP_DAYS = 365   # 전체 데이터 보관 기간 (검색/이력용)
QUERIES = ["M&A", "인수합병", "경영권 인수", "지분 매각"]
# 매일경제·한국경제 기사가 검색 결과 순위에 밀려 빠지지 않도록 매체별로 따로 한 번 더 검색한다.
SITES = ["mk.co.kr", "hankyung.com"]
SITE_QUERIES = ["M&A", "인수합병", "경영권 인수", "지분 매각", "매각 본입찰", "사모펀드 인수"]


def to_kst_stamp(pub):
    """RSS의 발행 시각(GMT)을 한국시간 'YYYYMMDDHHMM' 문자열로 바꾼다. 실패하면 빈 문자열."""
    try:
        d = parsedate_to_datetime(pub)
        if d.tzinfo is None:
            d = d.replace(tzinfo=dt.timezone.utc)
        d = d.astimezone(dt.timezone.utc) + dt.timedelta(hours=9)
        return d.strftime("%Y%m%d%H%M")
    except Exception:
        return ""


def fetch_query(q):
    """구글 뉴스 RSS 검색 (무료, 별도 인증 불필요)."""
    url = f"https://news.google.com/rss/search?q={quote(q)}+when:2d&hl=ko&gl=KR&ceid=KR:ko"
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    items = []
    for it in root.findall(".//item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        pub = (it.findtext("pubDate") or "").strip()
        src_el = it.find("source")
        source = src_el.text.strip() if src_el is not None and src_el.text else ""
        if title and link:
            items.append({"title": title, "link": link, "pubDate": pub, "pub": to_kst_stamp(pub), "source": source})
    return items


# 스팸·도박 사이트가 뉴스 검색에 섞여 들어오는 것을 막는다.
SPAM_RE = re.compile(r"(카지노|슬롯|토토|도박|바카라|먹튀|프리스핀|무료\s?플레이|사과게임|마작|포커(?!스)|배팅|베팅|룰렛|casino|slot|betting|roughnecks)", re.I)
# M&A와 관련 없는 기사는 제목에 아래 단어가 하나도 없다.
MA_RE = re.compile(r"(M&A|M&amp;A|인수|합병|매각|매물|경영권|지분|공개매수|바이아웃|PEF|사모펀드|분리매각|통매각|엑시트|분할|팔고|팔았|팔기로)", re.I)


def is_topic_page(title):
    """'인수합병 - TradingView' 처럼 기사가 아니라 검색어(주제) 페이지인 경우: 출처를 뗀 제목이 검색어 그대로이거나 너무 짧다."""
    head = re.sub(r"\s+[-–|]\s+[^-–|]{1,30}$", "", title.strip())
    h = re.sub(r"\s+", "", head)
    return len(h) <= 8 or h in {re.sub(r"\s+", "", q) for q in QUERIES}


def is_relevant(title, sources=(), link=""):
    blob = " ".join([title, link] + list(sources))
    if SPAM_RE.search(blob):
        return False
    if is_topic_page(title):
        return False
    return bool(MA_RE.search(title))


def norm_title(t):
    t = re.sub(r"[\[\]\(\)『』“”\"'…·,\.!?]", "", t)
    t = re.sub(r"\s+", "", t)
    return t


def similar(a, b):
    return SequenceMatcher(None, a, b).ratio()


def main():
    existing = []
    if os.path.exists(OUT):
        with open(OUT, encoding="utf-8") as f:
            existing = json.load(f)
    existing = [e for e in existing if not is_topic_page(e.get("title", ""))]   # 이미 저장된 주제 페이지도 정리

    now = dt.datetime.utcnow() + dt.timedelta(hours=9)  # 한국 시간
    cutoff = now - dt.timedelta(days=KEEP_DAYS)

    fresh = []
    seen_links = set()
    all_queries = list(QUERIES) + [f"{q} site:{s}" for s in SITES for q in SITE_QUERIES]
    for q in all_queries:
        try:
            got = fetch_query(q)
        except Exception as e:
            print(f"뉴스 조회 실패 ({q}): {e}")
            continue
        n_ok = 0
        for x in got:
            if x["link"] in seen_links:
                continue
            if is_relevant(x["title"], [x["source"]], x["link"]):
                seen_links.add(x["link"])
                fresh.append(x)
                n_ok += 1
        print(f"  [{q}] {len(got)}건 중 M&A 관련 {n_ok}건")
    for s_ in ("매일경제", "한국경제"):
        print(f"  {s_} 기사 {sum(1 for x in fresh if x['source'].startswith(s_))}건")

    # 오늘 새로 가져온 기사들을 "같은 이슈"끼리 제목 유사도로 묶는다.
    # (별도 AI 호출 없이 문자열 유사도로 대체 - 완벽하지 않지만 무료로 동작)
    groups = []
    for it in fresh:
        nt = norm_title(it["title"])
        matched = None
        for g in groups:
            if similar(nt, g["norm"]) > 0.55:
                matched = g
                break
        if matched:
            matched["items"].append(it)
        else:
            groups.append({"norm": nt, "items": [it]})

    print(f"오늘 수집 {len(fresh)}건 → 이슈 그룹 {len(groups)}개")

    existing_by_title = {e["title"]: e for e in existing}
    for g in groups:
        # 대표 기사는 같은 이슈 중 가장 최근에 나온 기사로 한다.
        g["items"].sort(key=lambda x: x.get("pub", ""), reverse=True)
        rep = g["items"][0]
        sources = sorted(set(x["source"] for x in g["items"] if x["source"]))
        key = rep["title"]
        g_pub = rep.get("pub", "")

        # 기존에 저장된 항목 중 제목이 비슷한 게 있으면 그 항목에 병합
        merged = existing_by_title.get(key)
        if not merged:
            for e in existing:
                if similar(norm_title(e["title"]), g["norm"]) > 0.55:
                    merged = e
                    break

        if merged:
            merged["sources"] = sorted(set(merged.get("sources", []) + sources))
            merged["outlet_count"] = len(merged["sources"]) or merged.get("outlet_count", 1)
            # 오늘도 계속 보도되고 있다는 뜻이므로 "마지막으로 보도된 날짜"를 갱신한다.
            # (first_seen은 최초 수집일 그대로 유지 — 이슈가 언제 시작됐는지 보존)
            merged["last_seen"] = now.strftime("%Y%m%d")
            # 같은 이슈의 더 새로운 기사가 나왔으면 제목·링크·시각을 최신 기사로 바꿔 위로 올린다.
            if g_pub and g_pub > merged.get("pub", merged.get("last_seen", "") + "0000"):
                merged["pub"] = g_pub
                merged["title"] = rep["title"]
                merged["link"] = rep["link"]
        else:
            new_e = {
                "title": rep["title"],
                "link": rep["link"],
                "sources": sources,
                "outlet_count": len(sources) or 1,
                "first_seen": now.strftime("%Y%m%d"),
                "last_seen": now.strftime("%Y%m%d"),
                "pub": g_pub or now.strftime("%Y%m%d%H%M"),
            }
            existing.append(new_e)
            existing_by_title[key] = new_e

    # 365일 지난 항목은 자동 삭제 (스팸·무관 기사는 과거 수집분까지 함께 제거)
    kept = []
    for e in existing:
        if not is_relevant(e.get("title", ""), e.get("sources", []), e.get("link", "")):
            continue
        try:
            seen = dt.datetime.strptime(e.get("first_seen", ""), "%Y%m%d")
        except ValueError:
            seen = now
        if seen >= cutoff:
            # 과거에 수집된 데이터에는 last_seen이 없을 수 있어 first_seen으로 채워준다.
            e.setdefault("last_seen", e.get("first_seen", ""))
            kept.append(e)

    # 가장 최근에 나온 기사가 위로 오도록 "기사 발행 시각"(한국시간)으로 정렬한다.
    # 발행 시각이 없는 예전 데이터는 마지막 보도 날짜의 0시로 보고, 같은 시각이면 매체 수가 많은 쪽이 먼저다.
    def sort_key(e):
        stamp = e.get("pub") or (e.get("last_seen", e.get("first_seen", "")) + "0000")
        return (stamp, e.get("outlet_count", 1))

    kept.sort(key=sort_key, reverse=True)

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(kept, f, ensure_ascii=False, indent=1)
    print(f"뉴스 {len(kept)}건 저장 (365일 경과분 자동 삭제)")


if __name__ == "__main__":
    main()
