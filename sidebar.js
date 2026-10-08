function escHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}

// 상단 내비게이션 메뉴
function renderSidebar(active) {
  const el = document.getElementById("topNav");
  if (!el) return;
  renderAuthBox(el);
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
