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

from translate_asia import jp_ko, cn_ko, co_ko

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
JP_EXCL = re.compile(r"自己株式|自社株|訂正|延長|結果|進捗|ストックオプション|新株予約権|投資口|ETF|REIT|インフラファンド|上場廃止|監理|整理|"
                     r"株式報酬|インセンティブ|従業員|役員|優先株式|持株会社体制|追加譲受価額|事後交付|臨時報告|質問|上場維持|株主優待|説明資料|補足|説明会|Q&A|公認会計士|監査法人|計上|業績|配当")
# 그룹 안에서만 하는 재편(완전자회사 흡수합병 등)은 표시만 해 두고 화면에서 기본으로 숨긴다
JP_INTERNAL = re.compile(r"完全子会社.*(?:吸収合併|吸収分割)|(?:連結)?子会社間|子会社同士|孫会社.*合併|簡易合併・略式合併")
CN_INTERNAL = re.compile(r"全资子公司之间|吸收合并全资子公司|全资子公司.*吸收合并|子公司.*少数股东|孙公司|内部.*(?:整合|划转)")


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
                            "ti": title, "c": cat, "u": link, "g": 1 if JP_INTERNAL.search(title) else 0, "x": (cell.get("kjPlace").get_text(" ", strip=True) if cell.get("kjPlace") else "")})
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
CN_EXCL = re.compile(r"更正|补充|进展|问询|回复|核查|法律意见|独立财务顾问|财务顾问|摘要|英文|延期|终止|取消|董事会决议|监事会|募集|回购|激励|担保|理财|委托|"
                     r"说明|督导|评估报告|审计报告|审阅报告|备考|提示性|免于|意见|承诺|自查|内幕|风险提示|停牌|复牌|会议|通知|章程|问答|报告书.*修订")


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
                got.append({"d": d, "code": a.get("secCode") or "", "co": a.get("secName") or "", "ti": title, "c": cat, "g": 1 if CN_INTERNAL.search(title) else 0,
                            "u": "http://static.cninfo.com.cn/" + (a.get("adjunctUrl") or ""), "id": aid})
            if not j.get("hasMore"):
                break
            time.sleep(0.6)
    # 같은 회사·같은 날·같은 분류의 여러 문서는 대표 한 건으로 묶는다 (가장 짧은 제목 = 본 공시일 가능성이 큼)
    grp = {}
    for x in got:
        k = (x["code"], x["d"], x["c"])
        if k not in grp or len(x["ti"]) < len(grp[k]["ti"]):
            n = grp[k]["n"] + 1 if k in grp else 1
            grp[k] = dict(x, n=n)
        else:
            grp[k]["n"] += 1
    out = list(grp.values())
    say("CN 골라낸 공시", len(got), "→ 묶음", len(out))
    return out


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
    db["jp"] = merge([x for x in db.get("jp", []) if jp_cat(x["ti"])], jp, lambda x: x["u"])
    db["cn"] = merge([x for x in db.get("cn", []) if "n" in x], cn, lambda x: (x["code"], x["d"], x["c"]))
    # 한국어 제목·회사명 (규칙 번역, 매번 새로 계산해 번역 규칙이 좋아지면 지난 공시에도 반영)
    rough = {"jp": 0, "cn": 0}
    for mkt, fn in (("jp", jp_ko), ("cn", cn_ko)):
        for x in db[mkt]:
            x["k"], r = fn(x["ti"])
            x["ck"] = co_ko(x["co"], mkt)
            x["r"] = 1 if r else 0
            rough[mkt] += r
    say("대략 번역", rough)
    db["updated"] = dt.datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    json.dump(db, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    say("누적 일본", len(db["jp"]), "중국", len(db["cn"]))
    for x in db["jp"][:8] + db["cn"][:8]:
        say(" ", x["d"], x["c"], x["co"], "|", x["ti"][:60])
    open(LOG, "w", encoding="utf-8").write("\n".join(log))


if __name__ == "__main__":
    main()
