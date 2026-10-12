import os
import re
import json
import datetime as dt
import xml.etree.ElementTree as ET
from difflib import SequenceMatcher
from urllib.parse import quote

import requests

OUT = "news.json"
KEEP_DAYS = 365   # 전체 데이터 보관 기간 (검색/이력용)
QUERIES = ["M&A", "인수합병", "경영권 인수", "지분 매각"]


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
            items.append({"title": title, "link": link, "pubDate": pub, "source": source})
    return items


# 스팸·도박 사이트가 뉴스 검색에 섞여 들어오는 것을 막는다.
SPAM_RE = re.compile(r"(카지노|슬롯|토토|도박|바카라|먹튀|프리스핀|무료\s?플레이|사과게임|마작|포커|배팅|베팅|룰렛|casino|slot|betting|roughnecks)", re.I)
# M&A와 관련 없는 기사는 제목에 아래 단어가 하나도 없다.
MA_RE = re.compile(r"(M&A|M&amp;A|인수|합병|매각|매물|경영권|지분|공개매수|바이아웃|PEF|사모펀드|분리매각|통매각|엑시트|분할|팔고|팔았|팔기로)", re.I)


def is_relevant(title, sources=(), link=""):
    blob = " ".join([title, link] + list(sources))
    if SPAM_RE.search(blob):
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

    now = dt.datetime.utcnow() + dt.timedelta(hours=9)  # 한국 시간
    cutoff = now - dt.timedelta(days=KEEP_DAYS)

    fresh = []
    for q in QUERIES:
        try:
            fresh.extend(x for x in fetch_query(q) if is_relevant(x["title"], [x["source"]], x["link"]))
        except Exception as e:
            print(f"뉴스 조회 실패 ({q}): {e}")

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
        rep = g["items"][0]
        sources = sorted(set(x["source"] for x in g["items"] if x["source"]))
        key = rep["title"]

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
        else:
            new_e = {
                "title": rep["title"],
                "link": rep["link"],
                "sources": sources,
                "outlet_count": len(sources) or 1,
                "first_seen": now.strftime("%Y%m%d"),
                "last_seen": now.strftime("%Y%m%d"),
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

    # 마지막으로 보도된 "날짜"를 1순위로, 그 날짜 안에서는 매체 수(인기)를 2순위로
    # 정렬한다. 이렇게 하면 며칠 전부터 누적 보도된 이슈가 오늘자 새 뉴스를
    # 영구적으로 밀어내지 못하고, 하루만 지나도 자연스럽게 순위에서 빠진다.
    def sort_key(e):
        try:
            last = dt.datetime.strptime(e.get("last_seen", e.get("first_seen", "")), "%Y%m%d")
        except ValueError:
            last = cutoff
        return (last, e.get("outlet_count", 1))

    kept.sort(key=sort_key, reverse=True)

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(kept, f, ensure_ascii=False, indent=1)
    print(f"뉴스 {len(kept)}건 저장 (365일 경과분 자동 삭제)")


if __name__ == "__main__":
    main()
