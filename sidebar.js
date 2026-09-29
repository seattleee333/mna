function escHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}

function renderSidebar(active) {
  const el = document.getElementById("sidebar");
  if (!el) return;
  el.innerHTML =
    '<div class="side-head"><a href="index.html">M&amp;A 데일리</a></div>' +
    '<nav class="side-nav">' +
      '<a href="index.html" class="' + (active === "daily" ? "on" : "") + '">M&amp;A 데일리</a>' +
      '<a href="listings.html" class="' + (active === "listings" ? "on" : "") + '">매물·인수희망 리스트</a>' +
    '</nav>' +
    '<div class="side-news">' +
      '<div class="side-news-title">M&amp;A 인기뉴스</div>' +
      '<div id="sideNewsList" class="side-news-list">불러오는 중...</div>' +
    '</div>';

  fetch("news.json?t=" + Date.now())
    .then(r => (r.ok ? r.json() : []))
    .then(data => {
      const list = document.getElementById("sideNewsList");
      if (!list) return;
      if (!data || !data.length) {
        list.innerHTML = '<div class="side-empty">아직 수집된 뉴스가 없습니다.</div>';
        return;
      }
      list.innerHTML = data.slice(0, 10).map(n => {
        const meta = (n.sources && n.sources.length ? escHtml(n.sources.slice(0, 2).join(", ")) : "") +
          (n.outlet_count > 1 ? " · " + n.outlet_count + "곳 보도" : "");
        return '<a class="side-news-item" target="_blank" rel="noopener" href="' + escHtml(n.link) + '">' +
          '<span class="sn-title">' + escHtml(n.title) + '</span>' +
          '<span class="sn-meta">' + meta + '</span>' +
          '</a>';
      }).join("");
    })
    .catch(() => {
      const list = document.getElementById("sideNewsList");
      if (list) list.innerHTML = '<div class="side-empty">뉴스를 불러올 수 없습니다.</div>';
    });
}
