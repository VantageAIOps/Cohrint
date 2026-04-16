/* Agent Traces + DAG Visualization — traces.js
 * Loaded by app.html for the Traces view.
 * Uses safe DOM APIs (createElement/textContent) — no innerHTML with API data.
 */

(function() {
  'use strict';

  // ── Table helpers ────────────────────────────────────────────────────────────

  function tbodyMsg(msg) {
    var tbody = document.getElementById('tracesBody');
    if (!tbody) return;
    while (tbody.firstChild) tbody.removeChild(tbody.firstChild);
    var tr = document.createElement('tr');
    var td = document.createElement('td');
    td.setAttribute('colspan', '7');
    td.style.cssText = 'padding:32px;text-align:center;color:var(--text-muted);';
    td.textContent = msg;
    tr.appendChild(td);
    tbody.appendChild(tr);
  }

  function makeCell(text, extraStyle) {
    var td = document.createElement('td');
    td.style.cssText = 'padding:10px 14px;font-size:13px;' + (extraStyle || '');
    td.textContent = text;
    return td;
  }

  // ── loadTraces ───────────────────────────────────────────────────────────────

  window.loadTraces = function() {
    var periodEl = document.getElementById('tracesPeriodSel');
    var period = periodEl ? periodEl.value : '7';
    var tbody = document.getElementById('tracesBody');
    if (!tbody) return;
    tbodyMsg('Loading\u2026');

    window.apiFetch('/v1/analytics/traces?period=' + encodeURIComponent(period))
      .then(function(data) {
        var traces = (data && data.traces) || [];
        if (!traces.length) { tbodyMsg('No traces found for this period.'); return; }

        while (tbody.firstChild) tbody.removeChild(tbody.firstChild);
        traces.forEach(function(t) {
          var tr = document.createElement('tr');
          tr.style.borderTop = '1px solid var(--border)';

          tr.appendChild(makeCell(
            String(t.trace_id || '').slice(0, 8) + '\u2026',
            'font-family:monospace;font-size:12px;color:var(--text-muted);'
          ));
          tr.appendChild(makeCell(t.name || '\u2014'));
          tr.appendChild(makeCell(String(t.spans || 0), 'text-align:right;'));
          tr.appendChild(makeCell(
            t.cost != null ? '$' + Number(t.cost).toFixed(4) : '\u2014',
            'text-align:right;'
          ));
          tr.appendChild(makeCell(
            t.latency != null ? (Number(t.latency) / 1000).toFixed(2) + 's' : '\u2014',
            'text-align:right;'
          ));
          tr.appendChild(makeCell(
            t.started_at ? String(t.started_at).slice(0, 16) : '\u2014',
            'font-size:12px;color:var(--text-muted);'
          ));

          var tdBtn = document.createElement('td');
          tdBtn.style.cssText = 'padding:10px 14px;text-align:right;';
          var btn = document.createElement('button');
          btn.style.cssText = 'background:var(--accent);color:#fff;border:none;border-radius:6px;padding:4px 10px;font-size:12px;cursor:pointer;';
          btn.textContent = 'View DAG';
          btn.addEventListener('click', (function(tid) {
            return function() { openDag(tid); };
          })(t.trace_id));
          tdBtn.appendChild(btn);
          tr.appendChild(tdBtn);
          tbody.appendChild(tr);
        });
      })
      .catch(function() { tbodyMsg('Failed to load traces.'); });
  };

  // ── openDag / closeDag ───────────────────────────────────────────────────────

  window.openDag = function(traceId) {
    var modal = document.getElementById('dagModal');
    var titleEl = document.getElementById('dagTitle');
    var subtitleEl = document.getElementById('dagSubtitle');
    var detailEl = document.getElementById('dagSpanDetail');
    var svgEl = document.getElementById('dagSvg');
    if (!modal) return;

    modal.style.display = 'flex';
    titleEl.textContent = 'Trace: ' + String(traceId).slice(0, 8) + '\u2026';
    subtitleEl.textContent = 'Loading spans\u2026';
    if (detailEl) detailEl.style.display = 'none';
    while (svgEl.firstChild) svgEl.removeChild(svgEl.firstChild);

    window.apiFetch('/v1/analytics/traces/' + encodeURIComponent(traceId))
      .then(function(data) {
        var spans = (data && data.spans) || [];
        subtitleEl.textContent = spans.length + ' spans \u00b7 ' + String(traceId).slice(0, 16) + '\u2026';
        renderDag(spans);
      })
      .catch(function() { subtitleEl.textContent = 'Failed to load spans.'; });
  };

  window.closeDag = function() {
    var modal = document.getElementById('dagModal');
    if (modal) modal.style.display = 'none';
  };

  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') window.closeDag();
  });

  // ── renderDag ────────────────────────────────────────────────────────────────

  function renderDag(spans) {
    var svgEl = document.getElementById('dagSvg');
    if (!svgEl) return;
    while (svgEl.firstChild) svgEl.removeChild(svgEl.firstChild);

    if (!spans.length) {
      var t = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      t.setAttribute('x', '50%'); t.setAttribute('y', '50%');
      t.setAttribute('text-anchor', 'middle'); t.setAttribute('fill', '#888');
      t.textContent = 'No spans';
      svgEl.appendChild(t);
      return;
    }

    // Build index
    var byId = {};
    spans.forEach(function(s) { byId[s.id] = s; });

    // Find roots (no parent or parent outside this trace)
    var roots = spans.filter(function(s) { return !s.parent_id || !byId[s.parent_id]; });
    if (!roots.length) roots = [spans[0]];

    // BFS level assignment
    var levels = {};
    var visited = {};
    var queue = roots.map(function(r) { return { id: r.id, lv: 0 }; });
    while (queue.length) {
      var item = queue.shift();
      if (visited[item.id]) continue;
      visited[item.id] = true;
      levels[item.id] = item.lv;
      spans.forEach(function(s) {
        if (s.parent_id === item.id && !visited[s.id]) {
          queue.push({ id: s.id, lv: item.lv + 1 });
        }
      });
    }
    // Assign level 0 to any unvisited (disconnected)
    spans.forEach(function(s) { if (levels[s.id] === undefined) levels[s.id] = 0; });

    // Group by level
    var byLevel = {};
    var maxLevel = 0;
    spans.forEach(function(s) {
      var lv = levels[s.id];
      if (!byLevel[lv]) byLevel[lv] = [];
      byLevel[lv].push(s);
      if (lv > maxLevel) maxLevel = lv;
    });

    var NW = 160, NH = 52, HGAP = 28, VGAP = 64;

    // Calculate max row width for centering
    var maxRowW = 0;
    Object.keys(byLevel).forEach(function(lv) {
      var w = byLevel[lv].length * NW + (byLevel[lv].length - 1) * HGAP;
      if (w > maxRowW) maxRowW = w;
    });

    // Assign positions
    var positions = {};
    Object.keys(byLevel).forEach(function(lv) {
      var row = byLevel[lv];
      var rowW = row.length * NW + (row.length - 1) * HGAP;
      var offset = (maxRowW - rowW) / 2;
      row.forEach(function(s, i) {
        positions[s.id] = {
          x: offset + i * (NW + HGAP),
          y: Number(lv) * (NH + VGAP) + VGAP / 2
        };
      });
    });

    var svgW = maxRowW + 48;
    var svgH = (maxLevel + 1) * (NH + VGAP) + VGAP;
    svgEl.setAttribute('viewBox', '0 0 ' + svgW + ' ' + svgH);
    svgEl.setAttribute('height', String(svgH));

    var ns = 'http://www.w3.org/2000/svg';

    // Arrow marker
    var defs = document.createElementNS(ns, 'defs');
    var marker = document.createElementNS(ns, 'marker');
    marker.setAttribute('id', 'dag-arrow');
    marker.setAttribute('markerWidth', '8');
    marker.setAttribute('markerHeight', '6');
    marker.setAttribute('refX', '7');
    marker.setAttribute('refY', '3');
    marker.setAttribute('orient', 'auto');
    var arrowPath = document.createElementNS(ns, 'path');
    arrowPath.setAttribute('d', 'M0,0 L0,6 L8,3 z');
    arrowPath.setAttribute('fill', '#555');
    marker.appendChild(arrowPath);
    defs.appendChild(marker);
    svgEl.appendChild(defs);

    var providerColors = { anthropic: '#e8a87c', openai: '#74b49b', google: '#7eb8f7' };

    // Draw edges
    spans.forEach(function(s) {
      if (!s.parent_id || !positions[s.parent_id] || !positions[s.id]) return;
      var pp = positions[s.parent_id];
      var cp = positions[s.id];
      var x1 = pp.x + NW / 2, y1 = pp.y + NH;
      var x2 = cp.x + NW / 2, y2 = cp.y;
      var mid = (y1 + y2) / 2;
      var edge = document.createElementNS(ns, 'path');
      edge.setAttribute('d', 'M' + x1 + ',' + y1 + ' C' + x1 + ',' + mid + ' ' + x2 + ',' + mid + ' ' + x2 + ',' + y2);
      edge.setAttribute('fill', 'none');
      edge.setAttribute('stroke', '#444');
      edge.setAttribute('stroke-width', '1.5');
      edge.setAttribute('marker-end', 'url(#dag-arrow)');
      svgEl.appendChild(edge);
    });

    // Draw nodes
    spans.forEach(function(s) {
      var pos = positions[s.id];
      if (!pos) return;
      var col = providerColors[(s.provider || '').toLowerCase()] || '#9b8fd4';

      var rect = document.createElementNS(ns, 'rect');
      rect.setAttribute('x', String(pos.x));
      rect.setAttribute('y', String(pos.y));
      rect.setAttribute('width', String(NW));
      rect.setAttribute('height', String(NH));
      rect.setAttribute('rx', '7');
      rect.setAttribute('fill', '#1a1a2e');
      rect.setAttribute('stroke', col);
      rect.setAttribute('stroke-width', '1.5');
      rect.style.cursor = 'pointer';

      var label = document.createElementNS(ns, 'text');
      label.setAttribute('x', String(pos.x + NW / 2));
      label.setAttribute('y', String(pos.y + 19));
      label.setAttribute('text-anchor', 'middle');
      label.setAttribute('fill', '#ddd');
      label.setAttribute('font-size', '11');
      label.setAttribute('font-family', 'monospace');
      label.textContent = String(s.agent_name || s.model || s.provider || 'span').slice(0, 22);

      var sub = document.createElementNS(ns, 'text');
      sub.setAttribute('x', String(pos.x + NW / 2));
      sub.setAttribute('y', String(pos.y + 36));
      sub.setAttribute('text-anchor', 'middle');
      sub.setAttribute('fill', '#777');
      sub.setAttribute('font-size', '10');
      var costStr = s.cost_usd != null ? '$' + Number(s.cost_usd).toFixed(4) : '';
      var latStr = s.latency_ms != null ? ' \u00b7 ' + s.latency_ms + 'ms' : '';
      sub.textContent = costStr + latStr;

      function onNodeClick(span) {
        return function() { showSpanDetail(span); };
      }
      rect.addEventListener('click', onNodeClick(s));
      label.addEventListener('click', onNodeClick(s));

      svgEl.appendChild(rect);
      svgEl.appendChild(label);
      svgEl.appendChild(sub);
    });
  }

  function showSpanDetail(s) {
    var el = document.getElementById('dagSpanDetail');
    if (!el) return;
    el.style.display = 'block';
    // Build detail using text nodes only
    while (el.firstChild) el.removeChild(el.firstChild);

    function addPart(label, value) {
      var b = document.createElement('strong');
      b.textContent = label + ': ';
      el.appendChild(b);
      el.appendChild(document.createTextNode(value + '  '));
    }
    addPart('Span', String(s.id || '').slice(0, 16) + '\u2026');
    addPart('Model', s.model || '\u2014');
    addPart('Provider', s.provider || '\u2014');
    addPart('Tokens',
      String(s.prompt_tokens || 0) + '+' + String(s.completion_tokens || 0) +
      (s.cache_tokens ? '+' + s.cache_tokens + ' cache' : '')
    );
    addPart('Cost', '$' + Number(s.cost_usd || 0).toFixed(6));
    addPart('Latency', (s.latency_ms || '\u2014') + 'ms');
    addPart('Feature', s.feature || '\u2014');
  }

})();
