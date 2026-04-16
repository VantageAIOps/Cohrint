/**
 * cp-console.js — Cross-Platform AI Spend Console tab
 * Depends on: window.__cpRegister (one-time registration from app.html), Chart.js
 *
 * Security: all user-sourced values are set via textContent (never innerHTML).
 */
(function () {
  'use strict';

  // Claim apiFetch via the one-time registration handle. Once claimed the
  // handle is nulled in app.html — no other script can acquire it afterwards.
  var _fetch = null;
  if (typeof window.__cpRegister === 'function') {
    window.__cpRegister(function (fn) { _fetch = fn; });
  }
  function apiFetch(path, opts) {
    if (!_fetch) throw new Error('[cp-console] apiFetch not registered');
    return _fetch(path, opts);
  }

  // Chart instances — destroyed before re-creating on each data refresh
  var cpTrendChart    = null;
  var cpDoughnutChart = null;
  var cpDevChart      = null;

  // Live poll
  var cpLiveInterval  = null;
  var cpLiveRestart   = null; // backoff setTimeout handle — cleared on destroy
  var cpLiveErrors    = 0;

  // Period persistence
  var PERIOD_KEY = 'vantage_cp_period';
  function getSavedPeriod() {
    var v = parseInt(localStorage.getItem(PERIOD_KEY) || '30', 10);
    return [7, 30, 90].indexOf(v) >= 0 ? v : 30;
  }
  function savePeriod(d) { localStorage.setItem(PERIOD_KEY, String(d)); }

  // Provider colour map
  var COLORS = { claude_code: '#6366f1', copilot_chat: '#06b6d4', cursor: '#f59e0b', gemini_cli: '#10b981' };
  function pc(p) { return COLORS[p] || '#8b5cf6'; }

  function fmt2(n) { return n != null ? Number(n).toFixed(2) : '0.00'; }

  // Show/hide per-card error banners
  function showCardError(elId, msg) {
    var el = document.getElementById(elId);
    if (!el) return;
    el.style.display = 'block';
    el.textContent = '\u26A0 ' + msg;
  }
  function clearCardError(elId) {
    var el = document.getElementById(elId);
    if (el) { el.style.display = 'none'; el.textContent = ''; }
  }

  // ── KPI cards ─────────────────────────────────────────────────────────────
  function makeKpiCard(label, valueText, valueColor) {
    var card = document.createElement('div');
    card.className = 'kpi-card';
    var lbl = document.createElement('div');
    lbl.className = 'kpi-label';
    lbl.textContent = label;
    var val = document.createElement('div');
    val.className = 'kpi-value';
    val.textContent = valueText;
    if (valueColor) val.style.color = valueColor;
    card.appendChild(lbl);
    card.appendChild(val);
    return card;
  }

  function renderCpKpis(summary) {
    var el = document.getElementById('cp-kpis');
    if (!el) return;
    el.textContent = '';

    var budget = summary.budget || {};
    var pct = budget.budget_pct != null ? Math.round(budget.budget_pct) : null;
    var pctColor = pct == null ? null : pct >= 85 ? '#f87171' : pct >= 50 ? '#fb923c' : '#4ade80';
    var top = (summary.by_provider || [])[0] || {};
    var share = summary.total_cost_usd > 0 && top.cost
      ? ' ' + Math.round(top.cost / summary.total_cost_usd * 100) + '%' : '';

    el.appendChild(makeKpiCard('Total Spend', '$' + fmt2(summary.total_cost_usd), null));
    el.appendChild(makeKpiCard('Top Tool', (top.provider || '\u2014') + share, null));
    el.appendChild(makeKpiCard('Active Devs', String(summary.active_developers || '\u2014'), null));
    el.appendChild(makeKpiCard('MTD Budget', pct != null ? pct + '%' : '\u2014', pctColor));
  }

  // ── Trend chart ───────────────────────────────────────────────────────────
  function renderCpTrend(data) {
    clearCardError('cp-trend-error');
    var canvas = document.getElementById('cp-trend-canvas');
    if (!canvas) return;
    if (cpTrendChart) { cpTrendChart.destroy(); cpTrendChart = null; }

    cpTrendChart = new Chart(canvas.getContext('2d'), {
      type: 'line',
      data: {
        labels: data.days,
        datasets: (data.series || []).map(function (s) {
          return {
            label: s.provider,
            data: s.data,
            borderColor: pc(s.provider),
            backgroundColor: pc(s.provider) + '22',
            fill: true,
            tension: 0.3,
            pointRadius: 0,
          };
        }),
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          y: {
            stacked: true,
            beginAtZero: true,
            grid: { color: 'rgba(255,255,255,0.04)' },
            ticks: { color: '#6b7280', font: { size: 10 }, callback: function (v) { return '$' + Number(v).toFixed(2); } },
          },
          x: {
            grid: { display: false },
            ticks: { color: '#6b7280', font: { size: 9 }, maxTicksLimit: 8 },
          },
        },
        plugins: {
          legend: { position: 'bottom', labels: { color: '#9ca3af', boxWidth: 10, padding: 14, font: { size: 10 } } },
        },
        interaction: { mode: 'index' },
      },
    });
  }

  // ── Doughnut chart ────────────────────────────────────────────────────────
  function renderCpDonut(summary) {
    clearCardError('cp-donut-error');
    var canvas = document.getElementById('cp-donut-canvas');
    if (!canvas) return;
    if (cpDoughnutChart) { cpDoughnutChart.destroy(); cpDoughnutChart = null; }

    var items = (summary.by_provider || []).filter(function (p) { return (p.cost || 0) > 0; });
    if (!items.length) {
      var errEl = document.getElementById('cp-donut-error');
      if (errEl) { errEl.style.display = 'block'; errEl.textContent = 'No spend data for this period.'; }
      var staleL = document.getElementById('cp-donut-legend');
      if (staleL) staleL.textContent = '';
      return;
    }

    cpDoughnutChart = new Chart(canvas.getContext('2d'), {
      type: 'doughnut',
      data: {
        labels: items.map(function (p) { return p.provider; }),
        datasets: [{
          data: items.map(function (p) { return p.cost; }),
          backgroundColor: items.map(function (p) { return pc(p.provider); }),
          borderWidth: 2,
          borderColor: '#0d1117',
          hoverOffset: 6,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: '65%',
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: function (ctx) { return ctx.label + ': $' + ctx.parsed.toFixed(2); } } },
        },
      },
    });

    // Render compact legend below the canvas
    var legendEl = document.getElementById('cp-donut-legend');
    if (!legendEl) {
      legendEl = document.createElement('div');
      legendEl.id = 'cp-donut-legend';
      canvas.parentElement.insertAdjacentElement('afterend', legendEl);
    }
    legendEl.textContent = '';
    legendEl.style.cssText = 'display:flex;flex-wrap:wrap;justify-content:center;gap:8px 14px;margin-top:10px;width:100%';
    var total = items.reduce(function (s, p) { return s + (p.cost || 0); }, 0);
    items.forEach(function (p) {
      var pct = total > 0 ? Math.round(p.cost / total * 100) : 0;
      var item = document.createElement('div');
      item.style.cssText = 'display:flex;align-items:center;gap:5px;font-size:10px;color:#9ca3af';
      var dot = document.createElement('span');
      dot.style.cssText = 'width:8px;height:8px;border-radius:50%;background:' + pc(p.provider) + ';flex-shrink:0';
      var lbl = document.createElement('span');
      lbl.textContent = p.provider + ' ' + pct + '%';
      item.appendChild(dot);
      item.appendChild(lbl);
      legendEl.appendChild(item);
    });
  }

  // ── Data loading ──────────────────────────────────────────────────────────
  function loadCrossplatform(period) {
    savePeriod(period);
    updatePeriodButtons(period);

    apiFetch('/v1/cross-platform/summary?days=' + period)
      .then(function (d) { renderCpKpis(d); renderCpDonut(d); })
      .catch(function (e) {
        showCardError('cp-donut-error', 'Load failed: ' + String(e.message));
        var kpiEl = document.getElementById('cp-kpis');
        if (kpiEl) { kpiEl.textContent = ''; var err = document.createElement('div'); err.className = 'empty-state'; err.textContent = 'Failed to load metrics.'; kpiEl.appendChild(err); }
      });

    apiFetch('/v1/cross-platform/trend?days=' + period)
      .then(renderCpTrend)
      .catch(function (e) { showCardError('cp-trend-error', 'Load failed: ' + String(e.message)); });

    apiFetch('/v1/cross-platform/developers?days=' + period)
      .then(function (d) { renderCpDevTable(d.developers || []); })
      .catch(function (e) { showCardError('cp-dev-error', 'Load failed: ' + String(e.message)); });

    apiFetch('/v1/cross-platform/connections')
      .then(renderCpConnections)
      .catch(function () {
        var el = document.getElementById('cp-connections');
        if (el) el.textContent = 'Failed to load connections.';
      });
  }

  function updatePeriodButtons(period) {
    document.querySelectorAll('.cp-period').forEach(function (btn) {
      btn.classList.toggle('active', parseInt(btn.dataset.days, 10) === period);
    });
  }

  // ── Tab lifecycle (called by app.html nav()) ──────────────────────────────
  window.cpConsoleInit = function () {
    loadCrossplatform(getSavedPeriod());
    startCpLivePoll();
  };
  window.cpConsoleLoadPeriod = function (p) {
    loadCrossplatform(p);
  };
  window.cpConsoleDestroy = function () {
    stopCpLivePoll();
  };

  // ── Period button wiring ──────────────────────────────────────────────────
  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('.cp-period').forEach(function (btn) {
      btn.addEventListener('click', function () {
        loadCrossplatform(parseInt(btn.dataset.days, 10));
      });
    });

    // Close developer modal on overlay click
    var modal = document.getElementById('devDetailModal');
    if (modal) {
      modal.addEventListener('click', function (e) {
        if (e.target === modal) closeModal('devDetailModal');
      });
    }
  });

  // ── Developer table ───────────────────────────────────────────────────────
  function renderCpDevTable(devs) {
    clearCardError('cp-dev-error');
    var el = document.getElementById('cp-dev-table');
    if (!el) return;

    if (!devs.length) {
      el.textContent = 'No developer data for this period.';
      return;
    }

    var table = document.createElement('table');
    table.style.cssText = 'width:100%;border-collapse:collapse';

    var thead = table.createTHead();
    var hrow  = thead.insertRow();
    ['Developer', 'Team', 'Tools', 'Spend', 'Commits', '$/commit'].forEach(function (h) {
      var th = document.createElement('th');
      th.textContent = h;
      th.style.cssText = 'padding:4px 6px;text-align:left;font-size:10px;opacity:.5;font-weight:500;border-bottom:1px solid rgba(255,255,255,.08)';
      hrow.appendChild(th);
    });

    var tbody = table.createTBody();
    devs.forEach(function (d) {
      var row = tbody.insertRow();
      var hasId = !!d.developer_id;
      if (hasId) {
        row.dataset.devId    = d.developer_id;
        row.dataset.devEmail = d.developer_email || '';
        row.dataset.devTeam  = d.team || '';
        row.className = 'cp-dev-row';
        row.style.cursor = 'pointer';
      } else {
        row.title = 'Install vantage-agent to enable drill-down';
        row.style.opacity = '0.6';
      }

      var emailTd = row.insertCell();
      emailTd.textContent = d.developer_email || d.developer_id || '—';
      emailTd.style.cssText = 'padding:7px 6px;font-size:12px';

      var teamTd = row.insertCell();
      teamTd.textContent = d.team || '—';
      teamTd.style.cssText = 'padding:7px 6px;font-size:11px;opacity:.5';

      var toolsTd = row.insertCell();
      toolsTd.style.cssText = 'padding:7px 6px';
      (d.providers || []).forEach(function (p) {
        var badge = document.createElement('span');
        badge.textContent = p.replace(/_/g, ' ');
        badge.style.cssText = 'font-size:10px;background:' + pc(p) + '22;color:' + pc(p) + ';padding:1px 6px;border-radius:4px;margin-right:3px';
        toolsTd.appendChild(badge);
      });

      var spendTd = row.insertCell();
      spendTd.textContent = '$' + fmt2(d.total_cost);
      spendTd.style.cssText = 'padding:7px 6px;font-size:12px;color:#4ade80';

      var commitsTd = row.insertCell();
      commitsTd.textContent = String(d.commits || 0);
      commitsTd.style.cssText = 'padding:7px 6px;font-size:12px;opacity:.7';

      var costTd = row.insertCell();
      costTd.textContent = d.cost_per_commit != null ? '$' + d.cost_per_commit.toFixed(2) : '—';
      costTd.style.cssText = 'padding:7px 6px;font-size:12px;opacity:.7';
    });

    el.textContent = '';
    el.appendChild(table);

    el.querySelectorAll('.cp-dev-row').forEach(function (row) {
      row.addEventListener('click', function () {
        openDevModal(row.dataset.devId, row.dataset.devEmail, row.dataset.devTeam);
      });
    });
  }

  // ── Developer detail modal ────────────────────────────────────────────────
  function openDevModal(devId, devEmail, devTeam) {
    var modal = document.getElementById('devDetailModal');
    var title = document.getElementById('devDetailTitle');
    var body  = document.getElementById('devDetailBody');
    if (!modal || !title || !body) return;

    title.textContent = (devEmail || devId) + (devTeam ? ' (' + devTeam + ')' : '');
    body.textContent  = 'Loading\u2026';
    modal.classList.add('active');

    var days = (typeof period !== 'undefined' ? period : 30);
    apiFetch('/v1/cross-platform/developer/' + encodeURIComponent(devId) + '?days=' + days)
      .then(function (data) { renderDevModalBody(body, data, devEmail); })
      .catch(function (e) {
        body.textContent = '\u26A0 ' + (e.message || 'Failed to load');
      });
  }

  function renderDevModalBody(body, data, devEmail) {
    body.textContent = '';

    // 1. By-tool cost table
    var table = document.createElement('table');
    table.style.cssText = 'width:100%;border-collapse:collapse;margin-bottom:16px';
    var thead = table.createTHead();
    var hrow  = thead.insertRow();
    ['Tool', 'Spend', 'Input tokens', 'Output tokens'].forEach(function (h) {
      var th = document.createElement('th');
      th.textContent = h;
      th.style.cssText = 'padding:4px 8px;text-align:left;font-size:10px;opacity:.5;font-weight:500;border-bottom:1px solid rgba(255,255,255,.08)';
      hrow.appendChild(th);
    });
    var tbody = table.createTBody();
    (data.by_provider || []).forEach(function (p) {
      var row = tbody.insertRow();
      [p.provider, '$' + fmt2(p.cost), String(p.input_tokens || 0), String(p.output_tokens || 0)]
        .forEach(function (val, i) {
          var td = row.insertCell();
          td.textContent = val;
          td.style.cssText = 'padding:6px 8px;font-size:12px' + (i === 1 ? ';color:#4ade80' : ';opacity:.8');
        });
    });
    body.appendChild(table);

    // 2. Daily trend chart
    var chartTitle = document.createElement('div');
    chartTitle.className = 'card-title';
    chartTitle.textContent = 'Daily Trend';
    chartTitle.style.marginBottom = '8px';
    body.appendChild(chartTitle);

    var canvas = document.createElement('canvas');
    canvas.id = 'cp-dev-chart-canvas';
    canvas.height = 120;
    body.appendChild(canvas);

    if (data.daily_trend && data.daily_trend.length) {
      if (cpDevChart) { cpDevChart.destroy(); cpDevChart = null; }
      var trend = data.daily_trend.slice().reverse();
      cpDevChart = new Chart(canvas.getContext('2d'), {
        type: 'line',
        data: {
          labels: trend.map(function (t) { return t.day; }),
          datasets: [{
            label: 'Spend',
            data: trend.map(function (t) { return t.cost; }),
            borderColor: '#6366f1',
            backgroundColor: '#6366f133',
            fill: true,
            tension: 0.3,
            pointRadius: 2,
          }],
        },
        options: {
          responsive: true,
          scales: {
            y: { beginAtZero: true, ticks: { callback: function (v) { return '$' + Number(v).toFixed(2); } } },
            x: { ticks: { maxTicksLimit: 6 } },
          },
          plugins: { legend: { display: false } },
        },
      });
    }

    // 3. Productivity stats
    var prod = data.productivity || {};
    var prodGrid = document.createElement('div');
    prodGrid.style.cssText = 'display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:16px';
    [
      ['Commits',       prod.commits],
      ['Pull Requests', prod.pull_requests],
      ['Lines Added',   prod.lines_added],
      ['Lines Removed', prod.lines_removed],
      ['Active Time',   prod.active_time_s != null ? Math.round(prod.active_time_s / 60) + 'm' : null],
    ].forEach(function (item) {
      var box = document.createElement('div');
      box.style.cssText = 'background:rgba(255,255,255,.04);border-radius:8px;padding:10px;text-align:center';
      var lbl = document.createElement('div');
      lbl.textContent = item[0];
      lbl.style.cssText = 'font-size:10px;opacity:.5;margin-bottom:4px';
      var val = document.createElement('div');
      val.textContent = item[1] != null ? String(item[1]) : '—';
      val.style.cssText = 'font-size:18px;font-weight:600';
      box.appendChild(lbl);
      box.appendChild(val);
      prodGrid.appendChild(box);
    });
    body.appendChild(prodGrid);

    // 4. Recommendations section
    var recsSection = document.createElement('div');
    recsSection.style.cssText = 'margin-top:16px;padding-top:16px;border-top:1px solid rgba(255,255,255,.08)';
    var recsTitle = document.createElement('div');
    recsTitle.style.cssText = 'font-size:12px;font-weight:600;margin-bottom:8px;opacity:.7';
    recsTitle.textContent = 'COST RECOMMENDATIONS';
    recsSection.appendChild(recsTitle);
    body.appendChild(recsSection);

    apiFetch('/v1/admin/developers/recommendations').then(function(recData) {
      var recs   = (recData && recData.recommendations) || [];
      var devRec = recs.find(function(r) { return r.developer_email === devEmail; });

      function appendNote(text) {
        var p = document.createElement('p');
        p.style.cssText = 'font-size:11px;opacity:.4;margin:0';
        p.textContent = text;
        recsSection.appendChild(p);
      }

      if (!devRec) { appendNote('No optimization opportunities found.'); return; }

      var itemDefs = [];
      if (devRec.savings_opportunity_usd > 0) {
        itemDefs.push({ prefix: '\u2022 Est. monthly savings: ', highlight: '$' + fmt2(devRec.savings_opportunity_usd) });
      }
      if (devRec.cache_hit_rate_pct < 20) {
        itemDefs.push({ prefix: '\u2022 Low cache hit rate (' + Number(devRec.cache_hit_rate_pct).toFixed(1) + '%) \u2014 consider prompt caching' });
      }
      if (devRec.cost_per_pr > 5) {
        itemDefs.push({ prefix: '\u2022 High cost per PR ($' + fmt2(devRec.cost_per_pr) + ') \u2014 review prompt length' });
      }

      if (!itemDefs.length) { appendNote('No optimization opportunities found.'); return; }

      itemDefs.forEach(function(item) {
        var p = document.createElement('p');
        p.style.cssText = 'font-size:11px;margin:4px 0;opacity:.8';
        p.appendChild(document.createTextNode(item.prefix));
        if (item.highlight) {
          var span = document.createElement('span');
          span.style.color = '#4ade80';
          span.textContent = item.highlight;
          p.appendChild(span);
        }
        recsSection.appendChild(p);
      });
    }).catch(function() {
      var err = document.createElement('p');
      err.style.cssText = 'font-size:11px;opacity:.4;margin:0';
      err.textContent = 'Recommendations unavailable.';
      recsSection.appendChild(err);
    });
  }

  // ── Live feed ─────────────────────────────────────────────────────────────
  function renderCpLiveFeed(data) {
    var el  = document.getElementById('cp-live-feed');
    var dot = document.getElementById('cp-live-dot');
    if (!el) return;

    if (dot) dot.style.color = data.is_stale ? '#fb923c' : '#4ade80';

    var events = data.events || [];
    el.textContent = '';

    if (!events.length) {
      var empty = document.createElement('p');
      empty.textContent = 'No activity yet.';
      empty.style.cssText = 'font-size:12px;opacity:.4;padding:8px 0';
      el.appendChild(empty);
      return;
    }

    events.slice(0, 15).forEach(function (e) {
      var row = document.createElement('div');
      row.style.cssText = 'display:grid;grid-template-columns:1fr auto auto auto;gap:8px;align-items:center;padding:5px 0;border-bottom:1px solid rgba(255,255,255,.04);font-size:11px';

      var left = document.createElement('span');
      var providerLabel = (e.provider || '').replace(/_/g, ' ');
      var agentLabel    = e.agent_name && e.agent_name !== e.provider ? ' [' + e.agent_name + ']' : '';
      var teamLabel     = e.team ? ' \u00b7 ' + e.team : '';
      left.textContent = providerLabel + agentLabel + teamLabel + ' \u00b7 ' + (e.model || '');
      left.style.opacity = '0.8';

      var rate = document.createElement('span');
      rate.textContent = e.token_rate_per_sec ? (e.token_rate_per_sec.toFixed(0) + ' tok/s') : '';
      rate.style.cssText = 'opacity:0.5;font-size:10px';

      var cost = document.createElement('span');
      cost.textContent = '$' + fmt2(e.cost_usd);
      cost.style.color = '#4ade80';

      var ts = document.createElement('span');
      ts.textContent = e.timestamp ? String(e.timestamp).slice(11, 19) : '';
      ts.style.opacity = '0.4';

      row.appendChild(left);
      row.appendChild(rate);
      row.appendChild(cost);
      row.appendChild(ts);
      el.appendChild(row);
    });

    if (data.is_stale) {
      var staleNote = document.createElement('p');
      staleNote.textContent = '\u26A0 stale \u2014 no activity in last 5 min';
      staleNote.style.cssText = 'font-size:10px;color:#fb923c;margin-top:4px';
      el.appendChild(staleNote);
    }
  }

  // ── Live poll ─────────────────────────────────────────────────────────────
  function startCpLivePoll() {
    stopCpLivePoll();
    cpLiveErrors = 0;
    var jitter = Math.random() * 10000 - 5000;

    function tick() {
      apiFetch('/v1/cross-platform/live?limit=15')
        .then(function (data) {
          cpLiveErrors = 0;
          renderCpLiveFeed(data);
        })
        .catch(function () {
          cpLiveErrors++;
          if (cpLiveErrors >= 3) {
            stopCpLivePoll();
            cpLiveRestart = setTimeout(startCpLivePoll, 120000);
          }
        });
      // Also refresh Active Now panel on each live poll tick
      if (typeof window.loadActiveDevelopers === 'function') {
        window.loadActiveDevelopers();
      }
    }

    tick(); // fire immediately; don't wait 15s for first update
    cpLiveInterval = setInterval(tick, 15000 + jitter);
  }

  function stopCpLivePoll() {
    if (cpLiveInterval) { clearInterval(cpLiveInterval); cpLiveInterval = null; }
    if (cpLiveRestart)  { clearTimeout(cpLiveRestart);  cpLiveRestart  = null; }
  }

  // ── Connections ───────────────────────────────────────────────────────────
  function relativeTime(dateStr) {
    if (!dateStr) return '—';
    var ts = new Date(String(dateStr).replace(' ', 'T') + (String(dateStr).includes('Z') ? '' : 'Z')).getTime();
    if (isNaN(ts)) return '—';
    var diff = Date.now() - ts;
    if (diff < 0) return 'just now';
    var mins = Math.floor(diff / 60000);
    if (mins < 2)   return 'just now';
    if (mins < 60)  return mins + 'm ago';
    var hrs = Math.floor(mins / 60);
    if (hrs < 24)   return hrs + 'h ago';
    var days = Math.floor(hrs / 24);
    if (days < 30)  return days + 'd ago';
    return Math.floor(days / 30) + 'mo ago';
  }

  function isStaleDate(dateStr) {
    if (!dateStr) return true;
    var ts = new Date(String(dateStr).replace(' ', 'T') + (String(dateStr).includes('Z') ? '' : 'Z')).getTime();
    return isNaN(ts) || (Date.now() - ts) > 48 * 60 * 60 * 1000; // >48h = stale
  }

  function renderCpConnections(data) {
    var el = document.getElementById('cp-connections');
    if (!el) return;
    el.textContent = '';

    var billing = data.billing_connections || [];
    var otel    = data.otel_sources || [];

    if (!billing.length && !otel.length) {
      var p = document.createElement('p');
      p.style.cssText = 'font-size:12px;opacity:.4';
      var txt = document.createTextNode('No tools connected. ');
      var link = document.createElement('a');
      link.href = '#';
      link.textContent = 'Add a tool';
      link.onclick = function (e) { e.preventDefault(); if (window.nav) nav('integrations', link); };
      p.appendChild(txt);
      p.appendChild(link);
      el.appendChild(p);
      return;
    }

    function addRow(providerName, statusColor, dateStr) {
      var stale = isStaleDate(dateStr);
      var row = document.createElement('div');
      row.style.cssText = 'display:flex;justify-content:space-between;align-items:center;padding:6px 0;border-bottom:1px solid rgba(255,255,255,.04);font-size:12px';

      var left = document.createElement('span');
      left.style.cssText = 'display:flex;align-items:center;gap:6px';
      var dot = document.createElement('span');
      dot.style.cssText = 'width:7px;height:7px;border-radius:50%;flex-shrink:0;background:' + (stale ? '#fb923c' : statusColor);
      if (!stale && statusColor === '#4ade80') dot.style.boxShadow = '0 0 5px #4ade80';
      left.appendChild(dot);
      left.appendChild(document.createTextNode(providerName));

      var right = document.createElement('span');
      right.textContent = relativeTime(dateStr);
      right.style.cssText = 'font-size:10px;opacity:.45;white-space:nowrap';
      if (stale && dateStr) right.style.color = '#fb923c';

      row.appendChild(left);
      row.appendChild(right);
      el.appendChild(row);
    }

    billing.forEach(function (c) {
      var color = c.status === 'active' ? '#4ade80' : c.status === 'error' ? '#f87171' : '#fb923c';
      addRow(c.provider, color, c.last_sync_at);
    });
    otel.forEach(function (o) {
      addRow(o.provider + ' (OTel)', '#4ade80', o.last_data_at);
    });
  }

})();
