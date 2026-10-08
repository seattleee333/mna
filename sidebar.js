function escHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}

// 상단 내비게이션 메뉴
function renderSidebar(active) {
  const el = document.getElementById("topNav");
  if (!el) return;
  renderAuthBox(el);
  renderFooter();
  el.innerHTML =
    '<a href="deals.html" class="' + (active === "daily" ? "on" : "") + '">딜클로징 리스트</a>' +
    '<a href="listings.html" class="' + (active === "listings" ? "on" : "") + '">매물·인수희망 리스트</a>' +
    '<a href="sell.html" class="' + (active === "sell" ? "on" : "") + '">매각하기</a>';
}

// 오른쪽 패널: M&A 인기뉴스를 카드 형태로 표시한다 (메뉴와 분리된 영역).
function renderNewsPanel() {
  const el = document.getElementById("newsPanel");
  if (!el) return;
  el.innerHTML =
    '<div class="news-panel-title">M&amp;A 인기뉴스<a class="np-all" href="news.html">전체보기 ›</a></div>' +
    '<div id="newsCardList" class="news-card-list">불러오는 중...</div>';

  fetch("news.json?t=" + Date.now())
    .then(r => (r.ok ? r.json() : []))
    .then(data => {
      const list = document.getElementById("newsCardList");
      if (!list) return;
      if (!data || !data.length) {
        list.innerHTML = '<div class="side-empty">아직 수집된 뉴스가 없습니다.</div>';
        return;
      }
      const rows = pickDistinctNews(data, 10);
      const html = rows.map((n, i) => {
        const source = n.sources && n.sources.length ? escHtml(n.sources[0]) : "";
        const countBadge = n.outlet_count > 1 ? '<span class="nc-count">+' + (n.outlet_count - 1) + '</span>' : "";
        return '<a class="news-card' + (i >= 5 ? ' extra' : '') + '" target="_blank" rel="noopener" href="' + escHtml(n.link) + '">' +
          '<span class="nc-rank">' + (i + 1) + '</span>' +
          '<span class="nc-body">' +
            '<span class="nc-title">' + escHtml(n.title) + '</span>' +
            '<span class="nc-meta">' + source + countBadge + '</span>' +
          '</span>' +
          '</a>';
      }).join("");
      list.innerHTML = html + (rows.length > 5 ? '<button type="button" class="np-more" id="npMore">더보기 ▾</button>' : "");
      const more = document.getElementById("npMore");
      if (more) more.onclick = () => {
        const open = list.classList.toggle("expanded");
        more.textContent = open ? "접기 ▴" : "더보기 ▾";
      };
    })
    .catch(() => {
      const list = document.getElementById("newsCardList");
      if (list) list.innerHTML = '<div class="side-empty">뉴스를 불러올 수 없습니다.</div>';
    });
}

// 상단 오른쪽 로그인/로그아웃 표시
function renderAuthBox(navEl) {
  const A = window.MNA_AUTH;
  if (!A || !A.enabled()) return;
  let box = document.getElementById("authBox");
  if (!box) {
    box = document.createElement("div");
    box.id = "authBox";
    box.className = "auth-box";
    navEl.parentNode.appendChild(box);
  }
  const u = A.user();
  if (u) {
    box.innerHTML = '<span class="auth-name">' + escHtml(u.name || u.email || "회원") + '님</span>' +
      '<button type="button" class="auth-btn" id="logoutBtn">로그아웃</button>';
    document.getElementById("logoutBtn").onclick = () => { A.logout(); location.reload(); };
  } else {
    const next = location.pathname.split("/").pop() + location.search;
    box.innerHTML = '<a class="auth-btn primary" href="login.html?next=' + encodeURIComponent(next) + '">로그인 / 회원가입</a>';
  }
}

// 비슷한 이슈(같은 사건을 다룬 기사)가 겹치지 않도록 서로 다른 기사만 고른다.
const NEWS_STOP = new Set(["매각","인수","지분","투자","합병","회장","대표","M&A","억원","조원","추진","결정","검토","확정","나서","본격","관련","이상","올해","내년","위해","통해","따르면","기업","회사","그룹사","업계"]);
function newsTokens(title) {
  const t = String(title).replace(/\s+-\s+[^-]{1,20}$/, "");
  const toks = t.match(/[A-Za-z][A-Za-z0-9&]*|[0-9]+(?:\.[0-9]+)?[가-힣]*|[가-힣]+/g) || [];
  return new Set(toks.filter(w => w.length >= 2 && !NEWS_STOP.has(w) && !/^[0-9]/.test(w)));
}
function pickDistinctNews(list, limit) {
  const out = [], seen = [];
  for (const n of list) {
    const tk = newsTokens(n.title);
    let dup = false;
    for (const s of seen) {
      let c = 0; tk.forEach(w => { if (s.has(w)) c++; });
      if (c >= 2) { dup = true; break; }
    }
    if (dup) continue;
    out.push(n); seen.push(tk);
    if (out.length >= limit) break;
  }
  return out;
}

// 모든 페이지 공통 푸터 (회사 정보는 이 한 곳에서만 수정)
function renderFooter() {
  if (document.getElementById("contact")) return;
  const f = document.createElement("footer");
  f.className = "hfooter";
  f.id = "contact";
  f.innerHTML = `<div class="hfooter-in">
    <nav class="fnav">
      <a href="deals.html">딜클로징 리스트</a>
      <a href="listings.html">매물·인수희망</a>
      <a href="sell.html">매각하기</a>
      <a href="#">공지사항</a>
      <a href="#">자주 묻는 질문</a>
      <a href="#">이용약관</a>
      <a href="#">개인정보처리방침</a>
      <a href="mailto:contact@example.com">제휴·광고 문의</a>
    </nav>
    <div class="finfo">
      <span><b>[회사명]</b></span>
      <span>대표자: [대표자명]</span>
      <span>개인정보관리책임자: [성명]</span>
      <span>사업자등록번호: [000-00-00000]</span>
      <span>통신판매업신고: [신고번호]</span>
    </div>
    <div class="finfo">
      <span>주소: [사업장 주소]</span>
      <span>문의·제휴: [contact@example.com]</span>
      <span>전화: [000-0000-0000]</span>
    </div>
    <div class="fdisc">ALL ABOUT M&amp;A의 모든 정보는 DART 공시와 공개 보도를 자동 분류·요약한 참고 자료이며, 투자·거래 판단의 근거가 될 수 없습니다. 정확한 내용은 원문을 확인하세요.<br>
      기업가치 간이평가 결과는 입력값과 시장 가정에 따른 추정치로, 실제 거래 가격과 다를 수 있습니다.</div>
    <div class="fcopy">Copyright © [회사명] All rights reserved.</div>
  </div>`;
  document.body.appendChild(f);
}

// 기업 로고(동그라미). 로고가 없거나 불러오지 못하면 회사명 첫 글자 아바타로 대체한다.
const AVATAR_COLORS = ["#3457e0","#0f9d58","#e0733d","#8e44ad","#16a2b8","#d6336c","#5c7cfa","#2f9e44"];
function corpAvatar(code, name, cls) {
  const nm = String(name || "?").replace(/^\(주\)|^주식회사\s*/, "").trim();
  const ch = escHtml(nm.charAt(0) || "?");
  let h = 0; for (const c of nm) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  const color = AVATAR_COLORS[h % AVATAR_COLORS.length];
  const mono = '<span class="avatar-mono" style="background:' + color + '">' + ch + '</span>';
  const ok = code && /^[0-9A-Za-z]{6}$/.test(code);
  const img = ok ? '<img src="https://ssl.pstatic.net/imgstock/fn/real/logo/stock/Stock' + code + '.svg" alt="" loading="lazy" referrerpolicy="no-referrer" ' +
    'onerror="this.remove()" onload="if(this.naturalWidth<2)this.remove()">' : "";
  return '<span class="avatar ' + (cls || "") + '">' + mono + img + '</span>';
}
