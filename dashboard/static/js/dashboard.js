// Dashboard JS helpers

// ── Toast notification system ──────────────────────────────────────────────
const TOAST_ICONS = {
  success: 'fa-circle-check',
  error:   'fa-circle-xmark',
  warning: 'fa-triangle-exclamation',
  info:    'fa-circle-info',
};

function showToast(message, type = 'info', duration = 4000) {
  const container = document.getElementById('toast-container');
  if (!container) return;

  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.innerHTML = `
    <i class="fa ${TOAST_ICONS[type] || TOAST_ICONS.info}"></i>
    <span>${message}</span>
    <button class="toast-close" onclick="dismissToast(this.closest('.toast'))"><i class="fa fa-xmark"></i></button>
  `;
  container.appendChild(toast);

  if (duration > 0) {
    setTimeout(() => dismissToast(toast), duration);
  }
  return toast;
}

function dismissToast(toast) {
  if (!toast || toast._dismissing) return;
  toast._dismissing = true;
  toast.classList.add('toast-out');
  setTimeout(() => toast.remove(), 230);
}

// Global alias so inline scripts can call toast()
window.toast = showToast;

// ── Sidebar collapse / expand ───────────────────────────────────────────────
function toggleSidebar() {
  const sidebar = document.getElementById('sidebar');
  if (!sidebar) return;
  const collapsed = sidebar.classList.toggle('collapsed');
  try { localStorage.setItem('sidebar-collapsed', collapsed ? '1' : '0'); } catch {}
}

function openMobileSidebar() {
  const sidebar = document.getElementById('sidebar');
  const backdrop = document.getElementById('sidebar-backdrop');
  if (sidebar) sidebar.classList.add('mobile-open');
  if (backdrop) backdrop.classList.add('is-open');
  document.body.style.overflow = 'hidden';
}

function closeMobileSidebar() {
  const sidebar = document.getElementById('sidebar');
  const backdrop = document.getElementById('sidebar-backdrop');
  if (sidebar) sidebar.classList.remove('mobile-open');
  if (backdrop) backdrop.classList.remove('is-open');
  document.body.style.overflow = '';
}

window.toggleSidebar   = toggleSidebar;
window.openMobileSidebar  = openMobileSidebar;
window.closeMobileSidebar = closeMobileSidebar;

// ── Global guild picker dropdown ────────────────────────────────────────────
function toggleGuildPicker(event) {
  if (event) event.stopPropagation();
  const menu = document.getElementById('guild-picker-menu');
  const btn  = document.getElementById('guild-picker-button');
  if (!menu || !btn) return;
  const open = menu.classList.toggle('open');
  btn.setAttribute('aria-expanded', open ? 'true' : 'false');
}
function closeGuildPicker() {
  const menu = document.getElementById('guild-picker-menu');
  const btn  = document.getElementById('guild-picker-button');
  if (menu) menu.classList.remove('open');
  if (btn)  btn.setAttribute('aria-expanded', 'false');
}
document.addEventListener('click', e => {
  const wrap = document.getElementById('guild-picker-wrap');
  if (wrap && !wrap.contains(e.target)) closeGuildPicker();
});
window.toggleGuildPicker = toggleGuildPicker;
window.closeGuildPicker  = closeGuildPicker;

// ── Command palette (Ctrl+K / ⌘K) ───────────────────────────────────────────
const CMDK_PAGES = [
  { label: 'Overview',          href: '/',                 icon: 'fa-gauge-high',            group: 'Main' },
  { label: 'Guild Config',      href: '/config',           icon: 'fa-sliders',               group: 'Main' },
  { label: 'Assistant',         href: '/assistant',        icon: 'fa-robot',                 group: 'Main' },
  { label: 'Mod Cases',         href: '/moderation',       icon: 'fa-gavel',                 group: 'Moderation' },
  { label: 'Warnings',          href: '/warnings',         icon: 'fa-triangle-exclamation',  group: 'Moderation' },
  { label: 'Reports',           href: '/reports',          icon: 'fa-flag',                  group: 'Moderation' },
  { label: 'Auto-Mod',          href: '/automod',          icon: 'fa-shield-halved',         group: 'Moderation' },
  { label: 'Tickets',           href: '/tickets',          icon: 'fa-ticket',                group: 'Support' },
  { label: 'Community',         href: '/community',        icon: 'fa-users',                 group: 'Support' },
  { label: 'Welcome',           href: '/welcome',          icon: 'fa-door-open',             group: 'Support' },
  { label: 'Economy',           href: '/economy',          icon: 'fa-coins',                 group: 'Features' },
  { label: 'Levels & XP',       href: '/levels',           icon: 'fa-chart-line',            group: 'Features' },
  { label: 'Giveaways',         href: '/giveaways',        icon: 'fa-gift',                  group: 'Features' },
  { label: 'Polls',             href: '/polls',            icon: 'fa-square-poll-vertical',  group: 'Features' },
  { label: 'Reminders',         href: '/reminders',        icon: 'fa-bell',                  group: 'Features' },
  { label: 'Voice & Music',     href: '/voice-music',      icon: 'fa-headphones',            group: 'Features' },
  { label: 'Custom Commands',   href: '/custom-commands',  icon: 'fa-terminal',              group: 'Features' },
  { label: 'Permissions',       href: '/permissions',      icon: 'fa-lock',                  group: 'Features' },
  { label: 'GitHub Integration',href: '/integrations',     icon: 'fa-brands fa-github',      group: 'Integrations' },
  { label: 'GitLab Integration',href: '/integrations/gitlab', icon: 'fa-brands fa-gitlab',   group: 'Integrations' },
  { label: 'Knowledge Base',    href: '/knowledge',        icon: 'fa-brain',                 group: 'AI & Knowledge' },
  { label: 'Web Crawler',       href: '/knowledge?tab=crawl',    icon: 'fa-spider',         group: 'AI & Knowledge' },
  { label: 'Training',          href: '/knowledge?tab=training', icon: 'fa-graduation-cap', group: 'AI & Knowledge' },
  { label: 'Feedback',          href: '/knowledge?tab=feedback', icon: 'fa-star',           group: 'AI & Knowledge' },
  { label: 'Logout',            href: '/logout',           icon: 'fa-arrow-right-from-bracket', group: 'Account' },
];

let _cmdkSelected = 0;
let _cmdkFiltered = [];

function _cmdkEscape(s) {
  return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

function _cmdkScore(item, q) {
  if (!q) return 1;
  const label = item.label.toLowerCase();
  const group = (item.group || '').toLowerCase();
  if (label.startsWith(q)) return 100;
  if (label.includes(q)) return 60;
  if (group.includes(q)) return 30;
  // fuzzy: all query chars appear in order
  let i = 0;
  for (const c of label) { if (c === q[i]) i++; if (i >= q.length) break; }
  return i === q.length ? 10 : 0;
}

function _cmdkRender() {
  const container = document.getElementById('cmdk-results');
  if (!container) return;
  if (!_cmdkFiltered.length) {
    container.innerHTML = '<div class="cmdk-empty">No matches</div>';
    return;
  }
  container.innerHTML = _cmdkFiltered.map((item, i) => `
    <a href="${_cmdkEscape(item.href)}" class="cmdk-item ${i === _cmdkSelected ? 'cmdk-selected' : ''}" data-cmdk-index="${i}">
      <i class="fa ${_cmdkEscape(item.icon)} lead"></i>
      <span>${_cmdkEscape(item.label)}</span>
      <span class="cmdk-sub">${_cmdkEscape(item.group || '')}</span>
    </a>
  `).join('');
  // Keep selected in view
  const sel = container.querySelector('.cmdk-selected');
  if (sel && sel.scrollIntoView) sel.scrollIntoView({ block: 'nearest' });
}

function _cmdkUpdate() {
  const input = document.getElementById('cmdk-input');
  const q = (input?.value || '').trim().toLowerCase();
  _cmdkFiltered = CMDK_PAGES
    .map(item => ({ item, score: _cmdkScore(item, q) }))
    .filter(x => x.score > 0)
    .sort((a, b) => b.score - a.score)
    .map(x => x.item);
  _cmdkSelected = 0;
  _cmdkRender();
}

function openCmdK() {
  const overlay = document.getElementById('cmdk-overlay');
  const input   = document.getElementById('cmdk-input');
  if (!overlay || !input) return;
  overlay.classList.add('open');
  overlay.setAttribute('aria-hidden', 'false');
  input.value = '';
  _cmdkUpdate();
  setTimeout(() => input.focus(), 10);
}

function closeCmdK() {
  const overlay = document.getElementById('cmdk-overlay');
  if (!overlay) return;
  overlay.classList.remove('open');
  overlay.setAttribute('aria-hidden', 'true');
}

window.openCmdK  = openCmdK;
window.closeCmdK = closeCmdK;

// ── Initialisation ───────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {

  // Restore sidebar collapsed state
  try {
    if (localStorage.getItem('sidebar-collapsed') === '1') {
      const sidebar = document.getElementById('sidebar');
      if (sidebar) sidebar.classList.add('collapsed');
    }
  } catch {}

  // Auto-dismiss flash messages after 5 seconds
  document.querySelectorAll('.flash-msg').forEach(el => {
    setTimeout(() => {
      el.style.transition = 'opacity 0.3s ease';
      el.style.opacity = '0';
      setTimeout(() => el.remove(), 320);
    }, 5000);
  });

  // Copy-to-clipboard buttons
  document.querySelectorAll('[data-copy-text]').forEach(button => {
    button.addEventListener('click', async event => {
      event.preventDefault();
      event.stopPropagation();
      const text = button.getAttribute('data-copy-text') || '';
      const label = button.getAttribute('data-copy-label') || 'Value';
      if (!text) return;
      try {
        await navigator.clipboard.writeText(text);
        const original = button.innerHTML;
        button.innerHTML = '<i class="fa fa-check"></i> Copied';
        button.setAttribute('aria-label', `${label} copied`);
        showToast(`${label} copied to clipboard`, 'success', 2000);
        setTimeout(() => {
          button.innerHTML = original;
          button.setAttribute('aria-label', `Copy ${label}`);
        }, 1400);
      } catch {
        showToast('Copy failed — try manually', 'error');
      }
    });
  });

  // Open accordion section if URL has a matching hash
  const openAccordionForHash = () => {
    const hash = window.location.hash;
    if (!hash) return;
    const target = document.querySelector(hash);
    if (!target) return;
    const details = target.closest('details');
    if (details) details.open = true;
  };
  openAccordionForHash();
  window.addEventListener('hashchange', openAccordionForHash);

  // Highlight active nav link based on current pathname
  const path = window.location.pathname.split('?')[0];
  document.querySelectorAll('.sidebar-link').forEach(a => {
    const href = (a.getAttribute('href') || '').split('?')[0];
    if (href && href !== '/' && path.startsWith(href)) {
      a.classList.add('active');
    }
  });

  // Command palette input handlers
  const cmdkInput = document.getElementById('cmdk-input');
  if (cmdkInput) {
    cmdkInput.addEventListener('input', _cmdkUpdate);
    cmdkInput.addEventListener('keydown', e => {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        if (_cmdkFiltered.length) {
          _cmdkSelected = (_cmdkSelected + 1) % _cmdkFiltered.length;
          _cmdkRender();
        }
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        if (_cmdkFiltered.length) {
          _cmdkSelected = (_cmdkSelected - 1 + _cmdkFiltered.length) % _cmdkFiltered.length;
          _cmdkRender();
        }
      } else if (e.key === 'Enter') {
        e.preventDefault();
        const target = _cmdkFiltered[_cmdkSelected];
        if (target) window.location.href = target.href;
      } else if (e.key === 'Escape') {
        e.preventDefault();
        closeCmdK();
      }
    });
  }
  const cmdkResults = document.getElementById('cmdk-results');
  if (cmdkResults) {
    cmdkResults.addEventListener('mousemove', e => {
      const item = e.target.closest('[data-cmdk-index]');
      if (!item) return;
      const idx = parseInt(item.getAttribute('data-cmdk-index'), 10);
      if (!Number.isNaN(idx) && idx !== _cmdkSelected) {
        _cmdkSelected = idx;
        _cmdkRender();
      }
    });
  }

  // Keyboard shortcuts
  document.addEventListener('keydown', e => {
    // Ctrl/Cmd+K = open command palette
    if ((e.ctrlKey || e.metaKey) && (e.key === 'k' || e.key === 'K')) {
      e.preventDefault();
      openCmdK();
      return;
    }
    // Ctrl/Cmd+B = toggle sidebar (ignore if typing in cmdk)
    if ((e.ctrlKey || e.metaKey) && (e.key === 'b' || e.key === 'B')) {
      const active = document.activeElement;
      if (active && active.id === 'cmdk-input') return;
      e.preventDefault();
      toggleSidebar();
    }
    // Escape = close mobile sidebar / command palette
    if (e.key === 'Escape') {
      closeCmdK();
      closeMobileSidebar();
      closeGuildPicker();
    }
  });

  window.addEventListener('resize', () => {
    if (window.matchMedia('(min-width: 768px)').matches) {
      closeMobileSidebar();
    }
  });

  // Confirm before POST: data-confirm-msg (preferred) or legacy onsubmit="return confirm('…')"
  function wireFormConfirm(form, msg) {
    const onSubmit = e => {
      e.preventDefault();
      showConfirmDialog(msg, () => {
        form.removeEventListener('submit', onSubmit);
        if (typeof form.requestSubmit === 'function') {
          try {
            form.requestSubmit();
          } catch {
            form.submit();
          }
        } else {
          form.submit();
        }
      });
    };
    form.addEventListener('submit', onSubmit);
  }

  document.querySelectorAll('form[data-confirm-msg]').forEach(form => {
    const msg = form.getAttribute('data-confirm-msg');
    if (msg) wireFormConfirm(form, msg);
  });

  document.querySelectorAll('form[onsubmit]').forEach(form => {
    const attr = form.getAttribute('onsubmit') || '';
    const match = attr.match(/confirm\(['"](.+)['"]\)/);
    if (!match) return;
    const msg = match[1];
    form.removeAttribute('onsubmit');
    wireFormConfirm(form, msg);
  });
});

// ── Confirm dialog (replaces browser alert/confirm) ─────────────────────────
function showConfirmDialog(message, onConfirm, onCancel) {
  const existing = document.getElementById('db-confirm-overlay');
  if (existing) existing.remove();

  const overlay = document.createElement('div');
  overlay.id = 'db-confirm-overlay';
  overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.6);z-index:9998;display:flex;align-items:center;justify-content:center;backdrop-filter:blur(3px);animation:toast-in 0.18s ease;';
  overlay.innerHTML = `
    <div style="background:linear-gradient(180deg,#111e33,#0c1728);border:1px solid rgba(148,163,184,0.18);border-radius:1rem;padding:1.5rem;max-width:380px;width:90%;box-shadow:0 24px 60px rgba(0,0,0,0.6);">
      <div style="display:flex;align-items:center;gap:0.75rem;margin-bottom:1rem;">
        <div style="width:2rem;height:2rem;background:rgba(245,158,11,0.15);border-radius:0.5rem;display:flex;align-items:center;justify-content:center;flex-shrink:0;">
          <i class="fa fa-triangle-exclamation" style="color:#fbbf24;font-size:0.85rem;"></i>
        </div>
        <p style="color:#e5eefc;font-size:0.9rem;font-weight:500;line-height:1.4;">${message}</p>
      </div>
      <div style="display:flex;gap:0.75rem;justify-content:flex-end;">
        <button id="db-confirm-cancel" class="btn-secondary" style="font-size:0.8rem;padding:0.45rem 0.9rem;">Cancel</button>
        <button id="db-confirm-ok" class="btn-danger" style="font-size:0.8rem;padding:0.45rem 0.9rem;">Confirm</button>
      </div>
    </div>
  `;
  document.body.appendChild(overlay);

  const close = () => overlay.remove();
  overlay.querySelector('#db-confirm-cancel').addEventListener('click', () => {
    if (onCancel) onCancel();
    close();
  });
  overlay.querySelector('#db-confirm-ok').addEventListener('click', () => {
    if (onConfirm) onConfirm();
    close();
  });
  overlay.addEventListener('click', e => {
    if (e.target === overlay) {
      if (onCancel) onCancel();
      close();
    }
  });
  overlay.querySelector('#db-confirm-ok').focus();
}

window.showConfirmDialog = showConfirmDialog;
