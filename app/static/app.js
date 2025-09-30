const tableBody = document.querySelector('#devices tbody');
const gns3Div = document.getElementById('gns3');
const intervalSpan = document.getElementById('interval');
const scanNowBtn = document.getElementById('scanNowBtn');

async function fetchStatus() {
  try {
    const res = await fetch('/api/status');
    const data = await res.json();
    if (typeof data.scan_interval === 'number') {
      intervalSpan.textContent = data.scan_interval;
    }
    render(data);
  } catch (e) {
    console.error(e);
  }
}

function render(data) {
  const devices = data.devices || [];
  tableBody.innerHTML = '';
  for (const d of devices) {
    const tr = document.createElement('tr');
    tr.dataset.id = d.id;
    const status = d.up ? '🟢' : '🔴';
    const lastSeen = d.last_seen ? new Date(d.last_seen * 1000).toLocaleString() : '-';
    // Helpers for meters
    const clamp = (n) => Math.max(0, Math.min(100, Number.isFinite(n) ? n : 0));
    const meter = (pct) => {
      if (pct === null || pct === undefined || !isFinite(pct)) return '<div class="bar"><div class="fill" style="width:0%"></div></div>';
      const v = clamp(pct);
      const cls = v >= 85 ? 'fill err' : (v >= 65 ? 'fill warn' : 'fill');
      return `<div class="bar"><div class="${cls}" style="width:${v}%"></div></div>`;
    };

    // System metrics via SSH (pretty KPIs)
    let sysCell = '-';
    if (d.ssh_ok) {
      const users = typeof d.ssh_users_active === 'number' ? d.ssh_users_active : null;
      const cpu = typeof d.ssh_cpu_percent === 'number' ? d.ssh_cpu_percent : null;
      const mem = typeof d.ssh_mem_percent === 'number' ? d.ssh_mem_percent : null;
      const dsk = typeof d.ssh_disk_percent === 'number' ? d.ssh_disk_percent : null;
      sysCell = `
        <div class="kpi">
          <div class="kpi-row"><span class="label">Users</span><div class="val">${users ?? '-'}</div></div>
          <div class="kpi-row"><span class="label">CPU</span>${meter(cpu)}<div class="val">${cpu != null ? cpu.toFixed(0)+'%' : '-'}</div></div>
          <div class="kpi-row"><span class="label">RAM</span>${meter(mem)}<div class="val">${mem != null ? mem.toFixed(0)+'%' : '-'}</div></div>
          <div class="kpi-row"><span class="label">Disk</span>${meter(dsk)}<div class="val">${dsk != null ? dsk.toFixed(0)+'%' : '-'}</div></div>
        </div>`;
    }

    // GNS3 KPIs + link
    let gns3Cell = '-';
    if ((d.gns3_active || d.gns3_api_ok)) {
      const open = typeof d.gns3_projects_open === 'number' ? d.gns3_projects_open : null;
      const gcpu = typeof d.gns3_cpu_percent === 'number' ? d.gns3_cpu_percent : null;
      const gram = typeof d.gns3_mem_percent === 'number' ? d.gns3_mem_percent : null;
      const link = d.gns3_url ? `<a href="${d.gns3_url}" target="_blank" rel="noopener">Open</a>` : '';
      gns3Cell = `
        <div class="kpi">
          <div class="kpi-row cell-links">${link}${open != null ? `<span>Projects: ${open}</span>` : ''}</div>
          <div class="kpi-row"><span class="label">CPU</span>${meter(gcpu)}<div class="val">${gcpu != null ? gcpu.toFixed(0)+'%' : '-'}</div></div>
          <div class="kpi-row"><span class="label">RAM</span>${meter(gram)}<div class="val">${gram != null ? gram.toFixed(0)+'%' : '-'}</div></div>
        </div>`;
    }
    // IPs: show all discovered IPs if present
    const ipCell = Array.isArray(d.ips) && d.ips.length
      ? `<div class="ip-tags">${d.ips.map(ip => `<span class="tag">${ip}</span>`).join('')}</div>`
      : (d.ip || '');

    tr.innerHTML = `
      <td class="status">${status}</td>
      <td>${d.name || ''}</td>
      <td>${ipCell}</td>
      <td>${sysCell}</td>
      <td>${gns3Cell}</td>
      <td>${d.mac || ''}</td>
      <td>${lastSeen}</td>
      <td>
        ${d.up ? '' : `<button data-id="${d.id}" data-mac="${d.mac || ''}" data-bcast="${d.broadcast || ''}">Wake</button>`}
      </td>
    `;
    tableBody.appendChild(tr);
  }

  const g = data.gns3 || {};
  gns3Div.textContent = g.installed ? `GNS3: installiert (${Object.keys(g.versions||{}).join(', ')})` : 'GNS3: nicht gefunden';

  tableBody.querySelectorAll('button').forEach(btn => {
    btn.addEventListener('click', async () => {
      btn.disabled = true;
      const row = btn.closest('tr');
      const name = row?.children?.[1]?.textContent || '';
      const mac = btn.dataset.mac || '';
      showToast(`Sende WOL an ${name || d?.name || ''}${mac ? ' ('+mac+')' : ''}...`, 'info');
      try {
        const payload = { id: btn.dataset.id, mac: btn.dataset.mac, broadcast: btn.dataset.bcast };
        const res = await fetch('/api/wol', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
        const j = await res.json();
        if (!j.ok) {
          showToast('WOL fehlgeschlagen: ' + (j.error || 'Unbekannter Fehler'), 'error');
        }
        else {
          row?.classList.add('flash');
          setTimeout(() => row?.classList.remove('flash'), 1200);
          showToast('WOL gesendet' + (mac ? ' ('+mac+')' : ''), 'success');
        }
      } catch (e) {
        showToast('WOL Fehler: ' + e, 'error');
      } finally {
        btn.disabled = false;
      }
    });
  });
}

fetchStatus();
setInterval(fetchStatus, 3000);

if (scanNowBtn) {
  scanNowBtn.addEventListener('click', async () => {
    try {
      scanNowBtn.disabled = true;
      showToast('Starte Sofort-Scan...', 'info');
      const res = await fetch('/api/scan-now', { method: 'POST' });
      const data = await res.json();
      if (!data.ok) {
        showToast('Scan fehlgeschlagen: ' + (data.error || 'Unbekannter Fehler'), 'error');
      } else {
        render({ devices: data.devices, gns3: null });
        showToast('Scan abgeschlossen', 'success');
      }
    } catch (e) {
      showToast('Scan Fehler: ' + e, 'error');
    } finally {
      scanNowBtn.disabled = false;
    }
  });
}

// Toast helper
function showToast(msg, type = 'info') {
  const box = document.getElementById('toasts');
  if (!box) return;
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = msg;
  box.appendChild(el);
  setTimeout(() => { el.style.opacity = '0.0'; el.style.transition = 'opacity .3s'; }, 2500);
  setTimeout(() => { el.remove(); }, 3000);
}
