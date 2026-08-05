/* Anti-AI Protest Radar — dashboard renderer. Reads data.json written by each scan. */
'use strict';

const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"]/g,
  c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

const REGION = {
  sf_bay: 'SF / Bay Area', la: 'Los Angeles', us: 'United States',
  foreign: 'Outside US', unknown: 'Location unknown'
};

function ago(iso){
  if(!iso) return '—';
  const clean = String(iso).replace(' ', 'T');
  const ms = Date.now() - new Date(/[Z+]/.test(clean) ? clean : clean + 'Z').getTime();
  if(isNaN(ms)) return '—';
  const sec = ms / 1000;
  if(sec < 90) return 'just now';
  if(sec < 3600) return Math.round(sec / 60) + 'm ago';
  if(sec < 86400) return Math.round(sec / 3600) + 'h ago';
  return Math.round(sec / 86400) + 'd ago';
}

const scoreClass = s => s >= 90 ? 's-hi' : s >= 70 ? 's-mid' : 's-low';

function hostOf(url){
  try { return new URL(url).hostname.replace(/^www\./, ''); }
  catch { return url || ''; }
}

function prettyDate(iso){
  if(!iso) return null;
  const d = new Date(iso + 'T00:00:00');
  if(isNaN(d)) return iso;
  const out = d.toLocaleDateString('en-US',
    {weekday:'long', month:'long', day:'numeric', year:'numeric'});
  const days = Math.round((d - new Date(new Date().toDateString())) / 86400000);
  const rel = days === 0 ? 'TODAY' : days === 1 ? 'TOMORROW'
            : days > 1 ? `in ${days} days` : `${-days} days ago`;
  return `${out} <span class="rel">${rel}</span>`;
}

/* A labelled row. Missing values say so explicitly rather than vanishing —
   "not stated" is information; a blank line is just confusing. */
function field(label, value, missing){
  const known = value !== null && value !== undefined && value !== '';
  return `<div class="field${known ? '' : ' unknown'}">
      <div class="f-label">${label}</div>
      <div class="f-value">${known ? value : (missing || 'not stated in the source')}</div>
    </div>`;
}

function eventCard(e){
  const cls = (e.status || 'signal').toLowerCase();
  const links = (e.links || []).filter(l => l && l.url);
  const direct = links.filter(l => l.direct);
  const primary = direct[0] || links[0] || (e.url ? {url:e.url, direct:e.url_is_direct !== 0} : null);

  // Location
  const region = REGION[e.region] || e.region || '';
  // Title-case place names, but keep acronyms upper ("nyc" -> "NYC", not "Nyc").
  const ACRONYM = /^(nyc|sf|la|dc|dtla|us|usa|uk|soma)$/i;
  const place = e.place
    ? e.place.trim().split(/\s+/)
        .map(w => ACRONYM.test(w) ? w.toUpperCase()
                                  : w.charAt(0).toUpperCase() + w.slice(1))
        .join(' ')
    : '';
  const locationValue = place
    ? `<strong>${esc(place)}</strong><span class="sub">${esc(region)}</span>`
    : (e.region && e.region !== 'unknown' ? `<strong>${esc(region)}</strong>` : '');

  // Date + hour
  const dateValue = e.event_date
    ? `<strong>${prettyDate(e.event_date)}</strong>` +
      (e.event_time ? `<span class="sub time">at ${esc(e.event_time)}</span>`
                    : `<span class="sub">time not stated</span>`)
    : '';

  // The link for this specific protest
  let linkValue = '';
  if(primary && primary.direct){
    linkValue = `<a class="golink" href="${esc(primary.url)}" target="_blank"
       rel="noopener">Open this protest ↗</a>
       <span class="sub">${esc(hostOf(primary.url))}</span>`;
  } else if(primary){
    linkValue = `<a class="golink weak" href="${esc(primary.url)}" target="_blank"
       rel="noopener">Open source page ↗</a>
       <span class="sub warn">⚠ listing page, not a direct link to this protest</span>`;
  }

  // Sources — every distinct link behind this event
  const sourceList = links.length
    ? `<ul class="srclist">${links.map(l => `<li>
         <a href="${esc(l.url)}" target="_blank" rel="noopener">${esc(hostOf(l.url))}</a>
         <span class="via">${esc(l.source || '')}</span>
         ${l.direct ? '' : '<span class="tag-weak">listing</span>'}
       </li>`).join('')}</ul>`
    : ((e.sources || []).length
        ? `<div class="sub">${esc(e.sources.slice(0, 6).join(', '))}</div>` : '');

  const chips = [
    `<span class="chip chip-score ${scoreClass(e.score)}">${e.score}/100</span>`,
    `<span class="chip chip-${cls}">${esc(e.status)}</span>`,
    e.target && e.target !== 'general' ? `<span class="chip">🎯 ${esc(e.target)}</span>` : '',
    e.first_seen ? `<span class="chip">found ${ago(e.first_seen)}</span>` : '',
    e.alerted ? `<span class="chip chip-confirmed">📱 texted</span>` : ''
  ].filter(Boolean).join('');

  return `<article class="event ${cls}">
    <div class="chips">${chips}</div>
    <h3>${esc(e.title)}</h3>
    <div class="fields">
      ${field('📍 Location', locationValue, 'location not stated')}
      ${field('🗓 Date &amp; time', dateValue, 'no date announced yet')}
      ${field('🔗 Link to this protest', linkValue, 'no link available')}
      ${field(`📰 Sources (${links.length || e.source_count || 1})`, sourceList)}
    </div>
    ${(e.reasons || []).length
      ? `<details class="why-d"><summary>Why this was flagged</summary>
         <div class="why">${esc(e.reasons.join(' · '))}</div></details>` : ''}
  </article>`;
}

function render(d){
  const s = d.summary || {};
  const events = d.events || [];

  const confirmed = events.filter(e => e.status === 'CONFIRMED');
  const reported  = events.filter(e => e.status === 'REPORTED');
  const signals   = events.filter(e => e.status === 'SIGNAL');
  const upcoming  = events.filter(e => e.temporality === 'upcoming' ||
                                       (e.event_date && e.status !== 'REPORTED'));
  const bay       = events.filter(e => e.region === 'sf_bay' || e.region === 'la');

  // ---- header
  $('generated').innerHTML = `Last scan <b>${ago(d.generated_at)}</b>`;
  const cap = d.messages_per_day_cap ?? 5;
  $('alertline').innerHTML =
    `alerts to <b>${esc(d.alert_phone)}</b> via <b>${esc(d.alert_backend)}</b>
     <span class="sep">·</span> <b>${d.messages_today ?? 0}/${cap}</b> messages today
     <span class="sep">·</span> rescans every <b>12h</b>`;

  // ---- banner: the day's binary verdict
  const verdict = d.verdict ?? (confirmed.length ? 1 : 0);
  const banner = $('banner');
  if(verdict === 1){
    $('pulse').classList.add('hot');
    banner.className = 'banner banner-alert';
    $('bannerTitle').textContent =
      `VERDICT 1 — protest news found (${confirmed.length} confirmed)`;
    $('bannerSub').innerHTML =
      `<b>${s.alerts_sent_this_run || 0}</b> of ${cap} message${cap === 1 ? '' : 's'}
       sent to <b>${esc(d.alert_phone)}</b> on the latest scan
       (<b>${d.messages_today ?? 0}/${cap}</b> today). Details below.`;
  } else {
    banner.className = 'banner banner-clear';
    $('bannerTitle').textContent = 'VERDICT 0 — no genuine protest news';
    $('bannerSub').innerHTML =
      `No messages sent. Watching <b>${s.total_events || 0}</b> distinct events and
       <b>${s.total_tracked || 0}</b> raw signals across
       <b>${Object.keys(d.collector_stats || {}).length}</b> collectors.
       <b>${s.new_24h || 0}</b> new in the last 24h. If that flips to 1 you get
       <b>${cap}</b> texts with a link back here.`;
  }

  // ---- tiles
  $('tiles').innerHTML = [
    ['red',   s.confirmed,       'Confirmed'],
    ['amber', s.upcoming_events, 'Upcoming leads'],
    ['blue',  s.sf_bay,          'SF / Bay Area'],
    ['blue',  s.la,              'Los Angeles'],
    ['green', s.new_24h,         'New in 24h'],
    ['',      s.total_events,    'Events tracked'],
    ['',      s.total_tracked,   'Raw signals'],
    ['',      s.sources_polled,  'Items scanned']
  ].map(([c, n, l]) =>
    `<div class="tile ${c}"><div class="n">${n ?? 0}</div><div class="l">${l}</div></div>`
  ).join('');

  // ---- tabs + filtering
  const views = [
    ['confirmed', 'Confirmed',  confirmed],
    ['upcoming',  'Upcoming',   upcoming],
    ['bay',       'SF & LA',    bay],
    ['reported',  'Happened',   reported],
    ['signals',   'Weak signals', signals],
    ['all',       'Everything', events]
  ];
  let active = confirmed.length ? 'confirmed' : 'upcoming';

  const drawTabs = () => {
    $('tabs').innerHTML = views.map(([k, label, list]) =>
      `<button class="tab ${k === active ? 'active' : ''}" data-view="${k}">
        ${label}<span class="n">${list.length}</span></button>`).join('');
    $('tabs').querySelectorAll('.tab').forEach(btn =>
      btn.addEventListener('click', () => { active = btn.dataset.view; drawTabs(); drawEvents(); }));
  };

  const drawEvents = () => {
    const q = $('search').value.toLowerCase().trim();
    const list = (views.find(v => v[0] === active) || [,, []])[2]
      .filter(e => !q || (
        (e.title || '') + ' ' + (e.place || '') + ' ' + (e.region || '') + ' ' +
        (e.target || '') + ' ' + (e.sources || []).join(' ')
      ).toLowerCase().includes(q));

    $('events').innerHTML = list.length
      ? list.map(eventCard).join('')
      : `<div class="empty">${
          active === 'confirmed'
            ? 'Nothing confirmed. The radar keeps watching — you will be texted the moment that changes.'
            : 'No events match this view.'}</div>`;
  };

  $('search').addEventListener('input', drawEvents);
  drawTabs();
  drawEvents();

  // ---- collector health
  $('collectors').innerHTML = Object.entries(d.collector_stats || {})
    .sort((a, b) => b[1] - a[1])
    .map(([k, v]) => `<div class="collector ${v < 0 ? 'err' : v === 0 ? 'zero' : ''}">
        <span class="k">${esc(k)}</span>
        <span class="v">${v < 0 ? 'ERR' : v}</span></div>`).join('')
    || '<div class="empty">No collector stats yet.</div>';

  // ---- run history
  $('runs').innerHTML = (d.runs || []).map(r => `
    <div class="run ${r.alerts_sent ? 'alerted' : ''}">
      <span class="when">${ago(r.started_at)}</span>
      <span class="stat">${r.collected ?? 0} collected · ${r.new_signals ?? 0} new${
        r.alerts_sent ? ` · 📱 ${r.alerts_sent}` : ''}${r.error ? ' · ⚠️ error' : ''}</span>
    </div>`).join('') || '<div class="empty">No runs recorded yet.</div>';
}

fetch('data.json?t=' + Date.now())
  .then(r => {
    if(!r.ok) throw new Error('HTTP ' + r.status);
    return r.json();
  })
  .then(render)
  .catch(err => {
    $('banner').className = 'banner';
    $('bannerTitle').textContent = 'Could not load data.json';
    $('bannerSub').innerHTML =
      `Run <code>./run.sh</code> at least once, and serve this folder with
       <code>./serve.sh</code> — opening index.html straight from disk is blocked
       by the browser. <br>${esc(err.message || err)}`;
  });

// Keep a long-lived tab fresh between 12-hourly scans.
setTimeout(() => location.reload(), 10 * 60 * 1000);
