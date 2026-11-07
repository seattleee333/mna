"""오늘의 딜 카드뉴스(1080x1350 PNG 5장)를 만든다.

입력: daily/latest.json (build_daily_post.py 결과)
출력: post/<날짜>/card1.png ~ card5.png
"""
import os
import re
import sys
import json
import html
import datetime as dt

W, H = 1080, 1350
FONT = '"Noto Sans CJK KR","Noto Sans KR","Pretendard","Apple SD Gothic Neo","Malgun Gothic",sans-serif'
ACCENT = "#3457e0"
INK = "#15181e"
SUB = "#6b7280"
LINE = "#e5e7ec"
BG = "#f5f6f8"
SITE_NAME = "ALL ABOUT M&A"
SITE_URL = "seattleee333.github.io/mna"
YEAR_LABELS = ["5년 전", "4년 전", "3년 전", "2년 전", "최근 1년"]

esc = html.escape


def base(body, n):
    return f"""<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8"><style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{width:{W}px;height:{H}px;background:{BG};font-family:{FONT};color:{INK};-webkit-font-smoothing:antialiased}}
.card{{width:{W}px;height:{H}px;padding:84px 80px 72px;display:flex;flex-direction:column;position:relative;background:#fff}}
.top{{display:flex;justify-content:space-between;align-items:center;font-size:30px;font-weight:700;color:{SUB}}}
.top b{{color:{ACCENT};font-weight:900;letter-spacing:-.01em}}
.foot{{margin-top:auto;display:flex;justify-content:space-between;align-items:center;font-size:26px;color:{SUB};padding-top:28px;border-top:2px solid {LINE}}}
.foot b{{color:{INK};font-weight:800}}
.tag{{display:inline-block;font-size:30px;font-weight:800;color:{ACCENT};background:#eef1fd;border-radius:999px;padding:12px 28px}}
h1{{font-size:78px;line-height:1.28;font-weight:900;letter-spacing:-.03em;word-break:keep-all}}
.big{{font-size:150px;font-weight:900;color:{ACCENT};letter-spacing:-.04em;line-height:1.05}}
p{{word-break:keep-all}}
.mid{{flex:1;display:flex;flex-direction:column;justify-content:center;gap:36px}}
.name{{font-size:64px;font-weight:900;line-height:1.3;letter-spacing:-.02em;word-break:keep-all}}
.lbl{{font-size:30px;font-weight:700;color:{SUB}}}
.arrow{{font-size:72px;color:{ACCENT};font-weight:900}}
table{{width:100%;border-collapse:collapse;font-size:42px}}
th{{text-align:left;color:{SUB};font-weight:700;padding:30px 0;width:36%;border-bottom:2px solid {LINE};vertical-align:top}}
td{{font-weight:800;padding:30px 0;border-bottom:2px solid {LINE};word-break:keep-all}}
.note{{font-size:30px;color:{SUB};line-height:1.55;word-break:keep-all}}
.bars{{display:flex;align-items:flex-end;gap:26px;height:420px;margin-top:10px}}
.bar{{flex:1;display:flex;flex-direction:column;justify-content:flex-end;align-items:center;gap:12px;height:100%}}
.bar i{{display:block;width:100%;background:#c9d3f7;border-radius:14px 14px 0 0}}
.bar.last i{{background:{ACCENT}}}
.bar span{{font-size:34px;font-weight:800}}
.bar em{{font-style:normal;font-size:26px;color:{SUB};font-weight:600}}
.lead{{font-size:44px;line-height:1.5;font-weight:700;word-break:keep-all}}
.pill{{display:inline-block;font-size:34px;font-weight:800;border-radius:999px;padding:10px 26px;background:#eef1fd;color:{ACCENT}}}
</style></head><body><div class="card">
<div class="top"><span><b>{SITE_NAME}</b></span><span>{n}/5</span></div>
{body}
<div class="foot"><span><b>오늘의 M&amp;A</b> · 공시 사실만 정리</span><span>{SITE_URL}</span></div>
</div></body></html>"""


def md(date):
    d = dt.datetime.strptime(date, "%Y%m%d")
    return f"{d.month}월 {d.day}일"


def cards(data):
    p, tx, sec = data["pick"], data["text"], data.get("sector")
    date = data["date"]
    buyers = "\n".join(esc(b) for b in p["buyers"][:2]) if p["buyers"] else ""
    buyers_html = "<br>".join(esc(b) for b in p["buyers"][:2])
    amt = tx.get("amount_text") or ""
    out = []

    # 1. 표지
    c1 = f"""<div class="mid">
<div><span class="tag">오늘의 M&amp;A · {md(date)}</span></div>
<h1>{esc(tx['headline'])}</h1>
{f'<div class="big">{esc(amt)}</div>' if amt else ''}
</div>"""
    out.append(base(c1, 1))

    # 2. 누가 → 누구를
    verb = {"stake_in": "취득(인수)", "stake_out": "처분(매각)"}.get(p["kind"], p["cat"])
    c2 = f"""<div class="mid">
<div><div class="lbl">공시한 회사</div><div class="name">{buyers_html}</div></div>
<div class="arrow">↓ {esc(verb)}</div>
<div><div class="lbl">거래 대상</div><div class="name">{esc(p['target'] or '공시 원문 확인')}</div></div>
{f'<div><div class="lbl">공시 금액</div><div class="name" style="color:{ACCENT}">{esc(amt)}</div></div>' if amt else ''}
</div>"""
    out.append(base(c2, 2))

    # 3. 딜 정보
    mk = {"Y": "코스피", "K": "코스닥"}.get(p.get("market"), "기타")
    rows = [("공시일", f"{p['date'][:4]}.{p['date'][4:6]}.{p['date'][6:]}"), ("거래 유형", p["cat"]),
            ("회사", "·".join(p["buyers"][:2])), ("시장", mk)]
    if p.get("target"):
        rows.insert(2, ("대상", p["target"]))
    if amt:
        rows.insert(3, ("금액", amt))
    tbl = "".join(f"<tr><th>{esc(a)}</th><td>{esc(b)}</td></tr>" for a, b in rows)
    c3 = f"""<div class="mid"><div class="lbl" style="font-size:36px">이 공시의 핵심</div><table>{tbl}</table>
<p class="note">{esc(tx['explain'] or '인수 목적·지분율 등은 공시 원문에서 확인하세요.')}</p></div>"""
    out.append(base(c3, 3))

    # 4. 업종 흐름
    if sec and sec.get("years"):
        ys = sec["years"]
        mx = max(ys) or 1
        bars = "".join(
            f'<div class="bar{" last" if i == len(ys) - 1 else ""}"><span>{v}</span><i style="height:{max(6, int(300 * v / mx))}px"></i><em>{YEAR_LABELS[i]}</em></div>'
            for i, v in enumerate(ys))
        c4 = f"""<div class="mid"><div><span class="pill">{esc(sec['name'])}</span></div>
<div class="lead">{esc(tx['context'])}</div>
<div><div class="lbl" style="margin-bottom:14px">상장사 인수 공시 건수 (12개월 단위)</div><div class="bars">{bars}</div></div></div>"""
    else:
        c4 = f"""<div class="mid"><div class="lead">이번 딜은 아직 비교할 업종 통계가 충분하지 않아요.</div>
<p class="note">업종별 동향은 사이트에서 확인할 수 있어요.</p></div>"""
    out.append(base(c4, 4))

    # 5. 마무리
    c5 = f"""<div class="mid">
<h1 style="font-size:66px">더 많은 오늘의 딜,<br>업종별 흐름은<br><span style="color:{ACCENT}">{SITE_NAME}</span>에서</h1>
<p class="lead" style="font-weight:600;color:{SUB}">프로필 링크에서 확인하세요</p>
<p class="note">{esc(tx['note'])}<br>인수 목적·지분율 등 자세한 내용은 공시 원문을 확인하세요.</p>
</div>"""
    out.append(base(c5, 5))
    return out


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "daily/latest.json"
    data = json.load(open(src, encoding="utf-8"))
    outdir = os.path.join("post", data["date"])
    os.makedirs(outdir, exist_ok=True)
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        pg = b.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
        for i, h in enumerate(cards(data), 1):
            pg.set_content(h)
            pg.wait_for_timeout(150)
            pg.screenshot(path=os.path.join(outdir, f"card{i}.png"))
        b.close()
    print("카드", outdir, sorted(os.listdir(outdir)))


if __name__ == "__main__":
    main()
