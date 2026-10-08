"""더벨(thebell.co.kr) M&A 관련 기사 제목·링크 수집 — 구글 뉴스 RSS(공개) 사용. 본문은 가져오지 않는다."""
import re
import json
import datetime as dt
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from urllib.parse import quote

import requests

OUT = "thebell.json"
QUERIES = ["site:thebell.co.kr M&A", "site:thebell.co.kr 인수", "site:thebell.co.kr 매각"]
KEYS = ("M&A", "인수", "매각", "합병", "지분", "경영권", "엠앤에이", "매물", "PEF", "사모펀드", "인수합병")


def fetch(q):
    url = f"https://news.google.com/rss/search?q={quote(q)}+when:14d&hl=ko&gl=KR&ceid=KR:ko"
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    out = []
    for it in ET.fromstring(r.content).findall(".//item"):
        title = (it.findtext("title") or "").strip()
        src = it.find("source")
        if src is None or not ("thebell" in (src.get("url") or "").lower() or "더벨" in (src.text or "")):
            continue
        title = re.sub(r"\s*-\s*(더벨|thebell)\s*$", "", title, flags=re.I)
        try:
            pub = parsedate_to_datetime(it.findtext("pubDate")).astimezone(dt.timezone(dt.timedelta(hours=9)))
        except Exception:
            continue
        out.append({"title": title, "link": (it.findtext("link") or "").strip(), "pubDate": pub.isoformat()})
    return out


def main():
    items = {}
    for q in QUERIES:
        try:
            for x in fetch(q):
                if any(k in x["title"] for k in KEYS):
                    items.setdefault(x["title"], x)
        except Exception as e:
            print("더벨 조회 실패:", q, e)
    rows = sorted(items.values(), key=lambda x: x["pubDate"], reverse=True)[:30]
    if rows:   # 실패 시 기존 파일 유지
        with open(OUT, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=1)
    print(f"더벨 M&A 기사 {len(rows)}건")


if __name__ == "__main__":
    main()
