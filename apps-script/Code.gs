/**
 * ALL ABOUT M&A — 소셜 로그인 검증 + 회원 정보를 구글시트에 저장하는 Apps Script
 * (구글시트 > 확장 프로그램 > Apps Script 에 붙여넣고, 웹 앱으로 배포하세요. 설정 방법: docs/로그인-설정.md)
 *
 * 스크립트 속성(프로젝트 설정 > 스크립트 속성)에 저장할 값 — 코드나 GitHub에는 절대 넣지 마세요:
 *   GOOGLE_CLIENT_ID, KAKAO_REST_KEY, KAKAO_CLIENT_SECRET(선택), NAVER_CLIENT_ID, NAVER_CLIENT_SECRET
 */
var SHEET = '회원';
var HEADERS = ['가입일시', '최근로그인', '로그인횟수', '로그인방식', '소셜고유번호', '이름', '이메일', '개인정보동의'];

function doPost(e) {
  try {
    var req = JSON.parse(e.postData.contents);
    if (req.action !== 'login') throw new Error('지원하지 않는 요청');
    var who = verify_(req);
    var row = upsert_(who);
    return json_({ ok: true, provider: who.provider, name: who.name, email: who.email, isNew: row.isNew });
  } catch (err) {
    return json_({ ok: false, error: String(err.message || err) });
  }
}

function doGet() { return json_({ ok: true, service: 'mna-auth' }); }

function json_(o) { return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON); }
function prop_(k) { return PropertiesService.getScriptProperties().getProperty(k) || ''; }
function fetchJson_(url, opt) {
  var r = UrlFetchApp.fetch(url, Object.assign({ muteHttpExceptions: true }, opt || {}));
  var j = JSON.parse(r.getContentText());
  if (r.getResponseCode() >= 400) throw new Error('소셜 로그인 확인 실패');
  return j;
}

function verify_(req) {
  var p = req.provider;
  if (p === 'google') {
    var t = fetchJson_('https://oauth2.googleapis.com/tokeninfo?id_token=' + encodeURIComponent(req.idToken));
    if (t.aud !== prop_('GOOGLE_CLIENT_ID')) throw new Error('잘못된 구글 토큰');
    return { provider: 'google', id: t.sub, name: t.name || '', email: t.email || '' };
  }
  if (p === 'kakao') {
    var form = { grant_type: 'authorization_code', client_id: prop_('KAKAO_REST_KEY'), redirect_uri: req.redirectUri, code: req.code };
    if (prop_('KAKAO_CLIENT_SECRET')) form.client_secret = prop_('KAKAO_CLIENT_SECRET');
    var tk = fetchJson_('https://kauth.kakao.com/oauth/token', { method: 'post', payload: form });
    var me = fetchJson_('https://kapi.kakao.com/v2/user/me', { headers: { Authorization: 'Bearer ' + tk.access_token } });
    var acc = me.kakao_account || {};
    return { provider: 'kakao', id: String(me.id), name: (acc.profile && acc.profile.nickname) || '', email: acc.email || '' };
  }
  if (p === 'naver') {
    var u = 'https://nid.naver.com/oauth2.0/token?grant_type=authorization_code&client_id=' + encodeURIComponent(prop_('NAVER_CLIENT_ID')) +
      '&client_secret=' + encodeURIComponent(prop_('NAVER_CLIENT_SECRET')) + '&code=' + encodeURIComponent(req.code) + '&state=' + encodeURIComponent(req.state);
    var nt = fetchJson_(u);
    var nm = fetchJson_('https://openapi.naver.com/v1/nid/me', { headers: { Authorization: 'Bearer ' + nt.access_token } });
    var r = nm.response || {};
    return { provider: 'naver', id: String(r.id), name: r.name || r.nickname || '', email: r.email || '' };
  }
  throw new Error('지원하지 않는 로그인 방식');
}

// 시트에서 수식으로 해석되지 않도록 앞에 ' 를 붙인다
function safe_(v) { v = String(v || ''); return /^[=+\-@]/.test(v) ? "'" + v : v; }

function upsert_(who) {
  var lock = LockService.getScriptLock(); lock.waitLock(20000);
  try {
    var ss = SpreadsheetApp.getActiveSpreadsheet();
    var sh = ss.getSheetByName(SHEET) || ss.insertSheet(SHEET);
    if (sh.getLastRow() === 0) { sh.appendRow(HEADERS); sh.setFrozenRows(1); }
    var now = Utilities.formatDate(new Date(), 'Asia/Seoul', 'yyyy-MM-dd HH:mm:ss');
    var last = sh.getLastRow();
    var data = last > 1 ? sh.getRange(2, 1, last - 1, HEADERS.length).getValues() : [];
    for (var i = 0; i < data.length; i++) {
      if (data[i][3] === who.provider && String(data[i][4]) === who.id) {
        sh.getRange(i + 2, 2, 1, 2).setValues([[now, Number(data[i][2] || 0) + 1]]);
        return { isNew: false };
      }
    }
    sh.appendRow([now, now, 1, who.provider, "'" + who.id, safe_(who.name), safe_(who.email), 'Y']);
    return { isNew: true };
  } finally { lock.releaseLock(); }
}
