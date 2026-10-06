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
            if domain_hint in r.url:
                return r.url  # 이미 실제 언론사 URL로 리다이렉트된 경우
            # 본문에 실제 URL이 그대로 노출돼 있는 경우 (가끔 있음)
            m = re.search(r'https?://(?:www\.)?' + re.escape(domain_hint) + r'/[^"\'\\<>\s]+', r.text)
            if m:
                return m.group(0)
            # 최후 수단: 구글 내부 API로 실제 URL 디코딩 시도
            try:
                return decode_google_news_link(session, r.text)
            except Exception as e:
                print(f"구글 뉴스 링크 디코딩 실패 [{google_link}]: {e}")
                return None
    except Exception as e:
        print(f"구글 뉴스 링크 조회 실패 [{google_link}]: {e}")
        return None


# 매일경제 [M&A 매물장터]는 기사 본문이 표가 아니라, A사/B사/C사(매물)·D사/E사/F사(인수희망)
# 식으로 여러 회사를 서술형 문단으로 소개하는 방식이다 (진단 결과 <table> 태그 자체가
# 본문에 없음을 확인함). 문단 단위로 나눠 매물/인수희망 여부를 키워드로 판별하고,
# 회사 표기(A사 등)·매출·희망 인수 금액을 정규식으로 뽑아낸다.
MK_SELL_KW = ["매물로 나왔다", "매물로 등록", "매물로 내놨다", "인수자를 찾아 나섰다",
              "인수자를 찾고 있다", "매수자를 찾는다", "매수자를 찾고 있다"]
MK_BUY_KW = ["인수를 희망", "인수를 추진", "인수를 검토", "인수를 타진", "인수에 관심"]


def _tidy(s, limit=40):
    s = re.sub(r"\s+", " ", s).strip(" ,.·")
    if len(s) > limit:
        s = s[:limit].rsplit(" ", 1)[0].strip(" ,.·")
    return s


def sell_industry(seg, label):
    """매물 문단에서 업종만 짧게 뽑는다.
    '…에 따르면 …수행하는 창호 제조사 A사가 인수자를 찾아 나섰다' → '창호 제조사'
    '연 매출 60억원의 물류 운송사 B사도 매물로 나왔다' → '물류 운송사'
    '…대상으로 기자재용품을 공급하는 A사가 매수자를 찾는다' → '기자재용품 공급'"""
    i = seg.find(label)
    if i <= 0:
        return ""
    pre = seg[:i]
    pre = re.sub(r"^.*?따르면\s*", "", pre)                                   # '28일 한국M&A거래소에 따르면'
    pre = re.sub(r"연\s*매출(?:은)?\s*[\d,.]+\s*(?:억|조)?\s*원?(?:대|가량|수준|이상|안팎)?\s*(?:의|인)?\s*", "", pre)
    pre = pre.strip(" ,")
    if "하는 " in pre:                       # '…일괄 수행하는 창호 제조사' → 마지막 명사구만
        pre = pre.rsplit("하는 ", 1)[1]
    m = re.search(r"([가-힣A-Za-z0-9·&\- ]+?)[을를]\s+([가-힣]+?)하는$", pre)  # '세정 장비를 제조하는'
    if m:
        pre = m.group(1).strip() + " " + m.group(2)
    else:
        pre = re.sub(r"하는$", "", pre)
    return _tidy(pre)


def buy_target(seg, label):
    """인수희망 문단에서 '어떤 회사를 인수하고 싶은지'만 뽑는다.
    'D사는 석산·크러셔 관련 업체 인수를 희망하고 있다' → '석산·크러셔 관련 업체'"""
    i = seg.find(label)
    if i < 0:
        return ""
    m = re.search(r"사(?:는|가)\s*(.+?)\s*인수(?:를|에)\s*(?:희망|추진|검토|타진|관심)", seg[i:])
    if not m:
        return ""
    t = re.sub(r"^.*?차원에서\s*", "", m.group(1))
    return _tidy(t, 50)


def parse_mk_prose(html):
    """인쇄용 페이지 본문(문단이 <br><br>로 구분된 서술형 기사)에서
    매물/인수희망 항목을 문단 단위로 추출한다."""
    paragraphs = re.split(r"(?:<br\s*/?>\s*){2,}", html)
    sell_items, buy_items = [], []
    NAME_RE = re.compile(r"\b([A-Z])사(?=[가-힣]|\b)")
    for p in paragraphs:
        text = BeautifulSoup(p, "html.parser").get_text(" ", strip=True)
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) < 15:
            continue
        # 한 <br><br> 블록 안에 회사가 여러 개(예: "D사는 ... 100억원이다. E사는 ...") 붙어
        # 나오는 경우가 있어, 회사 표기(A사/B사 등)가 나오는 위치마다 블록을 다시 잘라
        # 각 회사별로 따로 처리한다. 특정 회사를 명시하지 않는 도입부 요약 문단은
        # 회사 표기가 없어 자연히 걸러진다.
        matches = list(NAME_RE.finditer(text))
        for i, name_m in enumerate(matches):
            start = name_m.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            # "연매출 65억원의 ... B사도 매물로 나왔다"처럼 매출 등 설명이 회사명
            # 앞에 나오는 경우가 많아, 직전 문장 경계(마침표)부터 포함시켜
            # 매출/특징 정보를 놓치지 않도록 한다 (단, 이전 회사 문단까지 넘어가지
            # 않도록 그 이전 회사명 위치를 하한으로 둔다).
            lower_bound = matches[i - 1].start() if i > 0 else 0
            period_idx = text.rfind(". ", lower_bound, start)
            if period_idx != -1:
                ctx_start = period_idx + 2
            elif i == 0:
                ctx_start = 0  # 문단 내 첫 회사는 문단 시작부터 포함 (앞선 회사 문장과 섞일 일이 없음)
            else:
                ctx_start = start
            seg = text[ctx_start:end].strip()
            if len(seg) < 10:
                continue
            is_sell = any(k in seg for k in MK_SELL_KW)
            is_buy = any(k in seg for k in MK_BUY_KW)
            if not is_sell and not is_buy:
                continue
            label = name_m.group(1) + "사"
            if is_buy:
                amt_m = re.search(r"희망\s*인수\s*금액은\s*([^.]+?)(?:이다|다)?\.", seg)
                buy_items.append({
                    "label": label, "feature": seg[:220], "industry": buy_target(seg, label),
                    "budget": amt_m.group(1).strip() if amt_m else "",
                })
            else:
                rev_m = re.search(r"매출(?:은)?\s*([\d,]+)\s*억", seg)
                sell_items.append({
                    "label": label, "feature": seg[:220], "industry": sell_industry(seg, label),
                    "revenue": (rev_m.group(1) + "억원") if rev_m else "",
                })
    return sell_items, buy_items


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

        sell_items, buy_items = [], []
        if real_link:
            try:
                r = requests.get(real_link, headers=UA, timeout=20)
                r.raise_for_status()
                # 일반 기사 페이지(/news/view/<id>)는 표가 있는 경우 우선 시도
                s1, b1 = parse_mk_tables(r.text)
                sell_items, buy_items = s1, b1

                if not sell_items and not buy_items:
                    # 표가 없으면 인쇄용 페이지(/news/print/<id>)의 서술형 본문에서 추출한다.
                    m = re.search(r"/news/view/(\d+)", real_link)
                    if m:
                        print_url = f"https://stock.mk.co.kr/news/print/{m.group(1)}"
                        try:
                            pr = requests.get(print_url, headers=UA, timeout=20)
                            pr.raise_for_status()
                            ps, pb = parse_mk_tables(pr.text)
                            if not ps and not pb:
                                ps, pb = parse_mk_prose(pr.text)
                            sell_items, buy_items = ps, pb
                        except Exception as e:
                            print(f"매일경제 인쇄용 페이지 조회 실패 [{print_url}]: {e}")
            except Exception as e:
                print(f"매일경제 본문 조회 실패 [{real_link}]: {e}")
        else:
            print(f"매일경제 실제 기사 URL을 찾지 못함 (구글 리다이렉트만 있음): {it['title']}")

        base = {
            "outlet": "매일경제",
            "article_title": clean_title,
            "article_link": canonical_link,
            "pubDate": it["pubDate"],
        }
        if not sell_items and not buy_items:
            # 파싱에 실패해도 기사 자체는 놓치지 않도록 제목만으로 매물 1건 등록
            items_out.append({**base, "type": "sell", "industry": "", "revenue": "", "feature": clean_title})
        else:
            for row in sell_items:
                if isinstance(row, dict) and "구분" in row:  # parse_mk_tables 결과 (표 형태)
                    items_out.append({**base, "type": "sell",
                                       "label": row.get("구분", ""), "industry": row.get("업종", ""),
                                       "revenue": row.get("매출", ""), "feature": row.get("특징", "")})
                else:  # parse_mk_prose 결과 (서술형)
                    items_out.append({**base, "type": "sell", "industry": row.get("industry", ""),
                                       "label": row.get("label", ""), "ind_v": 2,
                                       "revenue": row.get("revenue", ""), "feature": row.get("feature", "")})
            for row in buy_items:
                if isinstance(row, dict) and "구분" in row:
                    items_out.append({**base, "type": "buy",
                                       "label": row.get("구분", ""), "form": row.get("형태", ""),
                                       "industry": row.get("업종", ""),
                                       "target_industry": row.get("인수희망대상", ""),
                                       "budget": row.get("인수가능금액", "")})
                else:
                    items_out.append({**base, "type": "buy", "form": "", "industry": "",
                                       "label": row.get("label", ""), "ind_v": 2,
                                       "target_industry": row.get("industry", ""),
                                       "feature": row.get("feature", ""),
                                       "budget": row.get("budget", "")})
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
        "type": "sell", "label": "", "industry": feature, "ind_v": 2, "revenue": revenue, "feature": feature,
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
        clean_title = re.sub(r"\s*[-|]\s*한국경제[^-|]*$", "", it["title"]).strip()
        add_hankyung_item(real_link, clean_title, it["pubDate"], existing_keys, items_out, added)


def migrate_summaries(rows):
    """예전에 기사 문장을 그대로 저장한 항목을, 저장돼 있는 문장(feature/target_industry)에서
    업종만 뽑은 짧은 요약으로 바꾼다 (기사를 다시 받지 않는다)."""
    for e in rows:
        if e.get("ind_v") == 2:
            continue
        label, kind = e.get("label", ""), e.get("type")
        if e.get("outlet") == "한국경제":
            e["industry"] = e.get("feature", "")
        elif label and kind == "sell" and not e.get("industry"):   # 표에서 온 항목은 업종이 이미 있다
            e["industry"] = sell_industry(e.get("feature", ""), label)
        elif label and kind == "buy" and not e.get("form"):        # 표에서 온 항목은 form 칸이 있다
            text = e.get("target_industry", "") or e.get("feature", "")
            e["feature"] = text
            e["target_industry"] = buy_target(text, label)
        e["ind_v"] = 2


def main():
    existing = []
    if os.path.exists(OUT):
        with open(OUT, encoding="utf-8") as f:
            existing = json.load(f)
    # 매물/인수 행 여러 개가 기사 하나에서 나올 수 있어, 중복 판단은 (매체, 기사 제목) 기준으로 한다.
    migrate_summaries(existing)
    existing_keys = {(e.get("outlet"), e.get("article_title")) for e in existing}
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
