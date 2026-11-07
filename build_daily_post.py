"""오늘의 M&A 포스팅 재료 만들기 (블로그 글 + 인스타·링크드인 문구 + 카드 이미지용 데이터).

흐름: 공시 딜(deals.json) 중에서 주목도 점수가 가장 높은 1건을 고른다 → 사실 항목만으로 문장을 만든다(AI 호출 없음)
      → daily/<날짜>.json, blog/<날짜>.html, blog/posts.json 저장.
카드 이미지는 render_cards.py 가 daily/<날짜>.json 을 읽어 만든다.

원칙: 공시에 없는 내용(인수 목적, 지분율 등)은 쓰지 않고 "공시 원문에서 확인"으로 안내한다.
      뉴스는 제목과 링크만 인용하고, 확정되지 않은 보도는 그렇게 표시한다.
"""
import html
import json
import math
import os
import re
import sys
import datetime as dt

from build_sector_board import KSIC2, SECTORS, sector_of_news, clean_title

SITE = "https://seattleee333.github.io/mna/"
KST = dt.timezone(dt.timedelta(hours=9))
KEEP_DAYS = 14   # 카드 이미지는 용량 때문에 최근 것만 남긴다 (글은 계속 남긴다)

# 자금 조달·펀드 출자·스팩 합병은 "인기 딜"에서 뺀다.
SKIP_CATEGORY = {"유상증자", "분할"}
RE_FUND = re.compile(r"투자조합|펀드|사모투자|합자회사|유동화|신탁|투자회사|벤처투자|SPC|조합$")
RE_SPAC = re.compile(r"스팩|기업인수목적")
CAT_W = {"경영권 변경 계약": 25, "공개매수": 25, "최대주주 변경": 20, "타법인 주식 취득·처분": 15,
         "영업양수도": 10, "합병": 8, "주식교환·이전": 8}


def load(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def short_name(n):
    n = re.sub(r"\(주\)|㈜|주식회사|\(株\)", "", n or "").strip()
    return re.sub(r"\s+", " ", n)


def final(w):
    """마지막 글자에 받침이 있는지 (한글이 아니면 없는 것으로 본다)."""
    c = (w or " ")[-1]
    return "가" <= c <= "힣" and (ord(c) - 0xAC00) % 28 != 0


def ga(w):
    return "이" if final(w) else "가"


def wa(w):
    return "과" if final(w) else "와"


def fmt_won(n):
    if not n:
        return ""
    if n >= 1e12:
        v = n / 1e12
        return (f"{v:.2f}".rstrip("0").rstrip(".")) + "조원"
    if n >= 1e8:
        return f"{round(n / 1e8):,}억원"
    return f"{round(n / 1e4):,}만원"


def key_of(name):
    k = re.sub(r"\(.*?\)|㈜|주식회사|\bAG\b|\bInc\.?|\bLtd\.?|\bCo\.?|\bCorp\.?|\bGroup\b|\bHoldings?\b|,", "", name or "", flags=re.I)
    k = re.sub(r"\s+", " ", k).strip()
    return k if len(k) >= 3 else ""


def news_hits(names, news, since):
    keys = [k for k in (key_of(n) for n in names) if k]
    hits = []
    for e in news:
        stamp = e.get("pub") or ((e.get("last_seen") or "") + "0000")
        if stamp[:8] < since:
            continue
        t = clean_title(e["title"], e.get("sources"))
        low = t.lower()
        if any(k.lower() in low for k in keys):
            hits.append({"title": t, "link": e["link"], "src": (e.get("sources") or [""])[0],
                         "n": e.get("outlet_count", 1), "pub": stamp})
    hits.sort(key=lambda x: (x["n"], x["pub"]), reverse=True)
    return hits


def candidates(deals, base_dates, news, since):
    groups = {}
    for e in deals:
        if e["date"] not in base_dates or e["category"] in SKIP_CATEGORY:
            continue
        tgt, buyer, amt = e.get("target") or "", e.get("buyer") or e["corp_name"], e.get("amount")
        if RE_SPAC.search(e["corp_name"] + tgt + buyer) or RE_FUND.search(tgt):
            continue
        # 같은 거래를 여러 회사가 각자 공시한 경우(대상·금액 동일)는 하나로 묶는다.
        gk = (e["category"], short_name(tgt), amt) if (tgt and amt) else (e["category"], e["corp_code"], e["rcept_no"])
        g = groups.setdefault(gk, {"deals": []})
        g["deals"].append(e)
    out = []
    for gk, g in groups.items():
        ds = g["deals"]
        e0 = ds[0]
        buyers = []
        for d in ds:
            b = short_name(d.get("buyer") or d["corp_name"])
            if b and b not in buyers:
                buyers.append(b)
        tgt = short_name(e0.get("target") or "")
        amt = e0.get("amount")
        names = buyers + ([tgt] if tgt else [])
        hits = news_hits(names, news, since)
        structured = bool(tgt and amt and e0.get("kind") in ("stake_in", "stake_out", "biz_in", "biz_out"))
        eok = (amt or 0) / 1e8
        score = (min(40, 10 * math.log10(max(eok, 1))) if amt else 0)
        score += min(40, sum(12 + 3 * h["n"] for h in hits[:3]))
        score += CAT_W.get(e0["category"], 5)
        score += 10 if structured else 0
        score += 5 if e0["market"] == "Y" else (3 if e0["market"] == "K" else 0)
        out.append({"score": round(score, 1), "buyers": buyers, "target": tgt, "amount": amt, "cat": e0["category"],
                    "kind": e0.get("kind"), "date": e0["date"], "market": e0["market"], "corp": e0["corp_name"],
                    "stock": e0.get("stock_code"), "rcept": e0["rcept_no"], "summary": e0.get("summary"),
                    "rcepts": [d["rcept_no"] for d in ds], "structured": structured, "news": hits[:3]})
    out.sort(key=lambda x: -x["score"])
    return out


def sector_for(pick, board, extra):
    """인수 회사의 업종(없으면 뉴스 제목)으로 업종 동향 항목을 찾는다."""
    sid = None
    for h in pick["news"]:
        sid = sector_of_news(h["title"])
        if sid:
            break
    if not sid:
        e = extra.get(pick["stock"] or "") or {}
        ind = str((e.get("company") or {}).get("induty_code") or "")
        sid = KSIC2.get(ind[:2])
    if not sid:
        return None
    s = next((x for x in board["sectors"] if x["id"] == sid), None)
    if not s:
        return None
    y = s["dart"]["years"]
    n = s["dart"]["n"]
    ratio = ((y[3] + y[4]) / 2 + 0.5) / (((y[0] + y[1] + y[2]) / 3) + 0.5)
    label = "표본 적음" if n < 15 else ("확대" if ratio >= 1.25 else ("축소" if ratio <= 0.75 else "유지"))
    return {"id": sid, "name": s["name"], "n": n, "years": y, "label": label, "median": s["dart"].get("median"),
            "news30": s["news"]["n"]}


KIND_TEXT = {
    "stake_in": "한 회사가 다른 회사의 지분(주식)을 사들이는 거래예요. 경영권을 확보하려는 경우도, 사업 협력이나 투자가 목적인 경우도 있어서 지분율과 인수 목적은 공시 원문에서 확인해야 해요.",
    "stake_out": "보유하던 다른 회사 지분을 파는 거래예요. 사업 정리나 자금 마련이 이유인 경우가 많은데, 정확한 이유는 공시 원문에서 확인해야 해요.",
    "biz_in": "회사 전체가 아니라 특정 사업 부문을 사들이는 거래(영업양수)예요.",
    "biz_out": "회사 전체가 아니라 특정 사업 부문을 파는 거래(영업양도)예요.",
}
CAT_TEXT = {
    "경영권 변경 계약": "회사를 이끄는 최대주주, 즉 경영권이 바뀌는 계약이 체결됐다는 공시예요. 계약 단계라서 대금 지급과 승인 절차가 끝나야 거래가 마무리돼요.",
    "최대주주 변경": "최대주주가 바뀌었다는 공시예요. 경영권이 다른 주체로 넘어갔을 가능성이 있어서 자주 주목받는 공시예요.",
    "공개매수": "공개매수는 시장 밖에서 '이 가격에 주식을 사겠다'고 공개적으로 제안하는 방식이에요. 경영권 인수나 지분 확대에 쓰여요.",
    "합병": "두 회사를 하나로 합치는 거래예요. 합병 비율과 일정은 공시 원문에서 확인할 수 있어요.",
    "영업양수도": "회사 전체가 아니라 특정 사업만 사고파는 거래예요.",
    "주식교환·이전": "주식을 서로 맞바꿔서 한 회사를 다른 회사의 자회사로 만드는 방식이에요.",
}


def build_text(p):
    b = "·".join(p["buyers"][:2]) + (" 등" if len(p["buyers"]) > 2 else "")
    amt = fmt_won(p["amount"])
    if p["structured"] and p["kind"] in ("stake_in", "biz_in"):
        verb = "인수"
        headline = f"{b}, {p['target']} {'지분 ' if p['kind'] == 'stake_in' else '사업 '}{amt} {verb}"
        short = f"{b}{ga(b)} {p['target']} {'지분을' if p['kind'] == 'stake_in' else '사업을'} {amt}에 인수한다고 공시했어요."
        if len(p["buyers"]) > 1:
            b1, b2 = p["buyers"][0], p["buyers"][1]
            two = f"{b1}{wa(b1)} {b2}"
            short = (f"{two}{ga(b2)} {p['target']} {'지분' if p['kind'] == 'stake_in' else '사업'} 취득을 공시했어요. "
                     f"두 회사가 같은 금액({amt})으로 공시했는데, 공동 취득인지 각자 취득인지는 공시 원문에서 확인해야 해요.")
    elif p["structured"]:
        headline = f"{b}, {p['target']} {'지분 ' if p['kind'] == 'stake_out' else '사업 '}{amt} 매각"
        short = f"{b}{ga(b)} {p['target']} {'지분을' if p['kind'] == 'stake_out' else '사업을'} {amt}에 판다고 공시했어요."
    else:
        headline = f"{p['corp']}, {p['cat']} 공시"
        short = p.get("summary") or f"{p['corp']}{ga(p['corp'])} {p['cat']}을 공시했어요."
    explain = KIND_TEXT.get(p["kind"]) if p["structured"] else CAT_TEXT.get(p["cat"], "")
    return headline, short, explain


def sector_line(sec):
    if not sec:
        return ""
    t = {"확대": "최근 2년 평균이 그 전 3년 평균보다 늘었어요", "유지": "최근 흐름은 이전과 비슷해요",
         "축소": "최근 2년 평균이 그 전 3년 평균보다 줄었어요", "표본 적음": "건수가 적어 흐름을 말하기 어려워요"}[sec["label"]]
    med = f" 거래 금액 중앙값은 {sec['median']:,}억원이에요." if sec.get("median") else ""
    return f"{sec['name']} 업종은 최근 5년간 상장사 인수 공시가 {sec['n']}건이었고, {t}.{med}"


def hashtags(p, sec):
    tags = ["#M&A", "#인수합병", "#기업인수", "#오늘의딜"]
    if sec:
        tags.append("#" + re.sub(r"[·\s]", "", sec["name"]))
    if p["structured"]:
        first = (key_of(p["target"]) or "").split(" ")[0]
        first = re.sub(r"[^\w가-힣]", "", first)
        if 2 <= len(first) <= 14:
            tags.append("#" + first)
    return [t for t in tags if len(t) > 1]


def make_post(pick, others, sec, news_top, today):
    headline, short, explain = build_text(pick)
    ctx = sector_line(sec)
    date_s = f"{today.month}월 {today.day}일"
    disp = f"공시일 {pick['date'][4:6]}/{pick['date'][6:8]}"
    link = f"{SITE}deals.html"
    amt = fmt_won(pick["amount"])
    note = "공개된 공시를 정리한 참고 정보이며 투자 권유가 아닙니다. 보도 내용은 확정되지 않았을 수 있어요."

    rel = ""
    if pick["news"]:
        rel = "\n".join(f"- {h['title']} ({h['src']})" for h in pick["news"][:2])

    li = [f"[오늘의 M&A] {headline}", "",
          f"· {disp} · {pick['cat']}"]
    if amt:
        li.append(f"· 금액: {amt}")
    li += ["", short]
    if explain:
        li.append(explain)
    if ctx:
        li += ["", ctx]
    li += ["", "공시에 적힌 사실만 정리했어요. 인수 목적·지분율 등 자세한 내용은 공시 원문을 확인하세요.",
           "", " ".join(hashtags(pick, sec))]
    linkedin = "\n".join(li)

    ig = [f"📌 오늘의 M&A · {date_s}", headline, "", short]
    if ctx:
        ig += ["", "📊 " + ctx]
    ig += ["", "공시 사실만 정리했어요. 자세한 내용은 공시 원문에서 확인하세요.",
           "더 많은 딜은 프로필 링크에서 🔗", "", " ".join(hashtags(pick, sec))]
    instagram = "\n".join(ig)

    return {"headline": headline, "short": short, "explain": explain, "context": ctx, "disp": disp, "amount_text": amt,
            "linkedin": linkedin, "linkedin_comment": f"더 많은 오늘의 딜과 업종별 동향은 여기서 볼 수 있어요 👉 {link}",
            "instagram": instagram, "note": note, "related": rel}


def blog_html(post_date, pick, others, sec, news_top, tx):
    esc = html.escape
    d = post_date
    title = f"[오늘의 M&A] {tx['headline']}"
    desc = tx["short"] + (" " + tx["context"] if tx["context"] else "")
    rows = [("공시일", f"{pick['date'][:4]}.{pick['date'][4:6]}.{pick['date'][6:]}"), ("거래 유형", pick["cat"]),
            ("인수(공시) 회사", "·".join(pick["buyers"]))]
    if pick["target"]:
        rows.append(("대상", pick["target"]))
    if tx["amount_text"]:
        rows.append(("금액", tx["amount_text"]))
    rows.append(("시장", {"Y": "코스피", "K": "코스닥"}.get(pick["market"], "기타")))
    tbl = "".join(f"<tr><th>{esc(a)}</th><td>{esc(b)}</td></tr>" for a, b in rows)
    rcept = "".join(f'<a target="_blank" rel="noopener" href="https://dart.fss.or.kr/dsaf001/main.do?rcpNo={esc(r)}">공시 원문{"" if i == 0 else " " + str(i + 1)}</a> '
                    for i, r in enumerate(pick["rcepts"][:3]))
    news_li = "".join(f'<li><a target="_blank" rel="noopener" href="{esc(h["link"])}">{esc(h["title"])}</a> <span>{esc("" if str(h["src"]).startswith("http") else h["src"])}</span></li>' for h in pick["news"][:3])
    others_li = "".join(f'<li><b>{esc(build_text(o)[0])}</b> <span>{esc(o["cat"])}</span></li>' for o in others)
    top_li = "".join(f'<li><a target="_blank" rel="noopener" href="{esc(h["link"])}">{esc(h["title"])}</a> <span>{esc("" if str(h["src"]).startswith("http") else h["src"])}</span></li>' for h in news_top)
    sec_html = ""
    if sec:
        sec_html = f'<h2>이 업종은 요즘 어떨까요</h2><p>{esc(tx["context"])}</p><p><a href="{SITE}sectors.html">업종별 동향 전체 보기 →</a></p>'
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)} · ALL ABOUT M&amp;A</title>
<meta name="description" content="{esc(desc[:150])}">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(desc[:150])}">
<link rel="stylesheet" href="../style.css">
<link rel="stylesheet" href="../home.css">
<link rel="stylesheet" href="blog.css">
</head>
<body>
<header class="topbar"><div class="topbar-inner"><a class="brand" href="../index.html">ALL ABOUT M&amp;A</a><nav class="top-nav" id="topNav"></nav></div></header>
<main class="post">
  <p class="post-meta"><a href="index.html">오늘의 M&amp;A</a> · {d.year}.{d.month:02d}.{d.day:02d}</p>
  <h1>{esc(tx['headline'])}</h1>
  <p class="lead">{esc(tx['short'])}</p>
  <table class="post-tbl">{tbl}</table>
  <p class="post-src">{rcept}</p>
  <h2>쉽게 풀어 보면</h2>
  <p>{esc(tx['explain'] or '공시에 적힌 사실을 그대로 정리했어요. 자세한 내용은 공시 원문에서 확인하세요.')}</p>
  <p>이 글은 공시에 있는 사실만 담았어요. 인수 목적이나 지분율 같은 내용은 공시 원문에서 확인해 주세요.</p>
  {sec_html}
  {('<h2>관련 보도</h2><ul class="post-list">' + news_li + '</ul><p class="post-note">기사 내용은 확정된 사실이 아닐 수 있어요. 제목만 소개하고 원문은 각 매체에서 확인하세요.</p>') if news_li else ''}
  {('<h2>오늘 함께 본 딜</h2><ul class="post-list">' + others_li + '</ul>') if others_li else ''}
  {('<h2>오늘 많이 보도된 M&amp;A</h2><ul class="post-list">' + top_li + '</ul>') if top_li else ''}
  <p class="post-cta"><a href="{SITE}deals.html">오늘의 딜클로징 리스트 보기</a> · <a href="{SITE}sectors.html">업종별 동향</a></p>
  <p class="post-note">{esc(tx['note'])}</p>
</main>
<script>window.MNA_BASE="../";</script>
<script src="../config.js"></script>
<script src="../auth.js"></script>
<script src="../sidebar.js"></script>
<script>renderSidebar("blog");</script>
</body>
</html>
"""


def top_news(news, since, exclude_titles):
    rows = []
    for e in news:
        stamp = e.get("pub") or ((e.get("last_seen") or "") + "0000")
        if stamp[:8] < since:
            continue
        t = clean_title(e["title"], e.get("sources"))
        t = re.sub(r"\s*:\s*[^:]{1,20}$", "", t) if re.search(r":\s*[^:]{1,20}$", t) and "?" not in t[-22:] else t
        if t in exclude_titles:
            continue
        rows.append((e.get("outlet_count", 1), stamp, t, e["link"], (e.get("sources") or [""])[0]))
    rows.sort(reverse=True)
    return [{"title": t, "link": l, "src": s, "n": n} for n, _, t, l, s in rows[:3]]


def main():
    force = "--force" in sys.argv
    today = dt.datetime.now(KST).date()
    stamp = today.strftime("%Y%m%d")
    out_json = f"daily/{stamp}.json"
    if os.path.exists(out_json) and not force:
        print("오늘 포스팅 재료가 이미 있어요(그대로 유지):", out_json)
        data = load(out_json)
    else:
        deals = load("deals.json", [])
        news = load("news.json", [])
        board = load("sector_board.json", {"sectors": []})
        extra = load("dart_extra_cache.json", {})
        dates = sorted({e["date"] for e in deals}, reverse=True)
        since = (today - dt.timedelta(days=4)).strftime("%Y%m%d")
        base = [d for d in dates if d >= (today - dt.timedelta(days=3)).strftime("%Y%m%d")][:2]
        cands = candidates(deals, set(base), news, since) if base else []
        if not cands:
            data = {"date": stamp, "pick": None, "message": "최근 공시에 올릴 만한 딜이 없어요."}
        else:
            pick, others = cands[0], cands[1:3]
            sec = sector_for(pick, board, extra)
            tx = make_post(pick, others, sec, [], today)
            used = {h["title"] for h in pick["news"]}
            ntop = top_news(news, since, used)
            tx = make_post(pick, others, sec, ntop, today)
            data = {"date": stamp, "base_dates": base, "pick": pick, "others": others, "sector": sec,
                    "news_top": ntop, "text": tx, "score_note": "공시 규모·보도량·거래 유형·시장으로 계산한 주목도 점수",
                    "blog": f"blog/{stamp}.html"}
        os.makedirs("daily", exist_ok=True)
        with open(out_json, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    with open("daily/latest.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)

    if data.get("pick"):
        os.makedirs("blog", exist_ok=True)
        page = blog_html(today, data["pick"], data["others"], data["sector"], data["news_top"], data["text"])
        with open(f"blog/{stamp}.html", "w", encoding="utf-8") as f:
            f.write(page)
        posts = load("blog/posts.json", [])
        posts = [p for p in posts if p["date"] != stamp]
        posts.insert(0, {"date": stamp, "title": "[오늘의 M&A] " + data["text"]["headline"],
                         "desc": data["text"]["short"], "file": f"{stamp}.html"})
        posts.sort(key=lambda p: p["date"], reverse=True)
        with open("blog/posts.json", "w", encoding="utf-8") as f:
            json.dump(posts, f, ensure_ascii=False, indent=1)
        print("선정:", data["text"]["headline"], "| 점수", data["pick"]["score"])
    else:
        print(data.get("message"))

    # 오래된 카드 이미지·일일 재료 정리
    cut = (today - dt.timedelta(days=KEEP_DAYS)).strftime("%Y%m%d")
    if os.path.isdir("post"):
        for name in os.listdir("post"):
            if name < cut:
                for fn in os.listdir(f"post/{name}"):
                    os.remove(f"post/{name}/{fn}")
                os.rmdir(f"post/{name}")


if __name__ == "__main__":
    main()
