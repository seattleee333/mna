"""일본·중국 상장사 M&A 공시 목록 → asia_deals.json (키 없이 공개 공시 목록만 사용)

- 일본: 도쿄증권거래소 TDnet 적시공시 목록(최근 약 1개월치 공개)에서 인수·TOB·합병·주식교환·사업양도 공시 제목을 골라낸다.
- 중국: 巨潮资讯(cninfo, 상하이·선전·베이징 거래소 공식 공시 사이트) 공시 검색에서 인수·자산 구조조정 공시를 골라낸다.
- 제목·회사명·원문 링크만 저장하고, 본문(PDF)은 받지 않는다. 받은 건은 누적 보관한다.
"""
import re
import json
import time
import datetime as dt

import requests
from bs4 import BeautifulSoup

OUT = "asia_deals.json"
LOG = "asia_log.txt"
UA = {"User-Agent": "Mozilla/5.0 (compatible; mna-research/1.0)"}
KST = dt.timezone(dt.timedelta(hours=9))
log = []


def say(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    log.append(s)


# ── 일본 TDnet ──
JP_RULES = [  # (분류, 정규식) — 위에서부터 먼저 맞는 것
    ("공개매수", r"公開買付"),
    ("주식교환", r"株式交換"),
    ("주식이전", r"株式移転"),
    ("합병", r"合併"),
    ("인수(자회사화)", r"子会社化|株式.*取得|持分.*取得|出資持分"),
    ("사업양수도", r"事業(?:の)?(?:譲受|譲渡|承継)|会社分割|吸収分割|新設分割"),
    ("자회사 변경", r"子会社の異動|孫会社の異動|特定子会社"),
    ("자본제휴", r"資本(?:業務)?提携"),
]
JP_EXCL = re.compile(r"自己株式|自社株|訂正|延長|結果|進捗|ストックオプション|新株予約権|投資口|ETF|REIT|インフラファンド|上場廃止|監理|整理")


def jp_cat(title):
    if JP_EXCL.search(title):
        return None
    for c, r in JP_RULES:
        if re.search(r, title):
            return c
    return None


def fetch_jp(days=31):
    got = []
    today = dt.datetime.now(KST).date()
    for k in range(days):
        d = today - dt.timedelta(days=k)
        ds = d.strftime("%Y%m%d")
        for page in range(1, 40):
            url = f"https://www.release.tdnet.info/inbs/I_list_{page:03d}_{ds}.html"
            try:
                r = requests.get(url, headers=UA, timeout=30)
            except Exception as e:
                say("JP", ds, page, "오류", type(e).__name__)
                break
            if r.status_code != 200:
                if page == 1 and k < 3:
                    say("JP", ds, "상태", r.status_code)
                break
            r.encoding = r.apparent_encoding or "utf-8"
            soup = BeautifulSoup(r.text, "html.parser")
            rows = soup.select("#main-list-table tr")
            if not rows:
                break
            n = 0
            for tr in rows:
                tds = tr.find_all("td")
                if len(tds) < 4:
                    continue
                n += 1
                cell = {(td.get("class") or [""])[0].split("-")[-1]: td for td in tds}
                get = lambda key, i: (cell.get(key) or tds[i]).get_text(" ", strip=True)
                title_td = cell.get("kjTitle") or tds[3]
                title = title_td.get_text(" ", strip=True)
                cat = jp_cat(title)
                if not cat:
                    continue
                a = title_td.find("a")
                link = "https://www.release.tdnet.info/inbs/" + a["href"] if a and a.get("href") else url
                got.append({"d": ds, "tm": get("kjTime", 0), "code": get("kjCode", 1)[:4], "co": get("kjName", 2),
                            "ti": title, "c": cat, "u": link, "x": (cell.get("kjPlace").get_text(" ", strip=True) if cell.get("kjPlace") else "")})
            if n == 0:
                break
            time.sleep(0.4)
    say("JP 골라낸 공시", len(got))
    return got


# ── 중국 cninfo ──
CN_URL = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
CN_RULES = [
    ("요약매수", r"要约收购"),
    ("자산 구조조정", r"重大资产重组|重大资产购买|重大资产出售|发行股份购买资产"),
    ("흡수합병", r"吸收合并|换股合并"),
    ("인수", r"收购.*(?:股权|股份|资产|公司)|购买.*股权|受让.*股权|增资.*控股|取得.*控制权"),
    ("매각", r"出售.*(?:股权|资产|子公司)|转让.*(?:股权|子公司)"),
    ("경영권 변경", r"控股股东.*(?:变更|拟变更)|实际控制人.*变更|控制权.*变更"),
]
CN_EXCL = re.compile(r"更正|补充|进展|问询|回复|核查意见|法律意见|独立财务顾问|摘要|英文|延期|终止|取消|关联交易的公告$|董事会决议|监事会|募集|回购|激励|担保|理财|委托")


def cn_cat(title):
    if CN_EXCL.search(title):
        return None
    for c, r in CN_RULES:
        if re.search(r, title):
            return c
    return None


def fetch_cn(days=31):
    got = []
    end = dt.datetime.now(KST).date()
    start = end - dt.timedelta(days=days)
    s = requests.Session()
    s.headers.update({**UA, "Origin": "http://www.cninfo.com.cn", "Referer": "http://www.cninfo.com.cn/new/commonUrl/pageOfSearch?url=disclosure/list/search",
                      "X-Requested-With": "XMLHttpRequest", "Accept": "application/json, text/javascript, */*; q=0.01"})
    seen = set()
    for key in ["收购", "重大资产重组", "吸收合并", "要约收购", "股权转让", "控制权变更"]:
        for page in range(1, 31):
            data = {"pageNum": page, "pageSize": 30, "column": "szse", "tabName": "fulltext", "plate": "", "stock": "", "searchkey": key,
                    "secid": "", "category": "", "trade": "", "seDate": f"{start}~{end}", "sortName": "", "sortType": "", "isHLtitle": "true"}
            try:
                r = s.post(CN_URL, data=data, timeout=30)
                j = r.json()
            except Exception as e:
                say("CN", key, page, "오류", type(e).__name__, getattr(r, "status_code", ""))
                break
            arr = j.get("announcements") or []
            if page == 1:
                say("CN", key, "전체", j.get("totalAnnouncement"), "첫 장", len(arr))
            if not arr:
                break
            for a in arr:
                title = re.sub(r"<.*?>", "", a.get("announcementTitle") or "")
                aid = a.get("announcementId")
                if aid in seen:
                    continue
                seen.add(aid)
                cat = cn_cat(title)
                if not cat:
                    continue
                t = a.get("announcementTime")
                d = dt.datetime.fromtimestamp(t / 1000, KST).strftime("%Y%m%d") if t else ""
                got.append({"d": d, "code": a.get("secCode") or "", "co": a.get("secName") or "", "ti": title, "c": cat,
                            "u": "http://static.cninfo.com.cn/" + (a.get("adjunctUrl") or ""), "id": aid})
            if not j.get("hasMore"):
                break
            time.sleep(0.6)
    say("CN 골라낸 공시", len(got))
    return got


def merge(old, new, key):
    m = {key(x): x for x in old}
    for x in new:
        m[key(x)] = x
    return sorted(m.values(), key=lambda x: (x["d"], x.get("tm", "")), reverse=True)


def main():
    try:
        db = json.load(open(OUT, encoding="utf-8"))
    except Exception:
        db = {"jp": [], "cn": []}
    jp = fetch_jp()
    cn = fetch_cn()
    db["jp"] = merge(db.get("jp", []), jp, lambda x: x["u"])
    db["cn"] = merge(db.get("cn", []), cn, lambda x: str(x.get("id") or x["u"]))
    db["updated"] = dt.datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    json.dump(db, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    say("누적 일본", len(db["jp"]), "중국", len(db["cn"]))
    for x in db["jp"][:8] + db["cn"][:8]:
        say(" ", x["d"], x["c"], x["co"], "|", x["ti"][:60])
    open(LOG, "w", encoding="utf-8").write("\n".join(log))


if __name__ == "__main__":
    main()
