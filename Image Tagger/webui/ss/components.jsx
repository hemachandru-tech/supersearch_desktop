/* Shared components — exported to window for cross-file use. */

const { useState, useEffect, useRef, useMemo } = React;

/* A media-tile placeholder that reads as a real photo without using copyrighted
   imagery. Deterministic gradient + light sweep + grain + faint glyph. */
function PhotoTile({ rec, ratio = '4 / 3', rounded = 12 }) {
  const isReal = rec.id && typeof rec.id === 'number';
  const [imgLoaded, setImgLoaded] = useState(false);
  const [imgError, setImgError] = useState(false);

  useEffect(() => {
    setImgLoaded(false);
    setImgError(false);
  }, [rec.id]);

  const [a, b] = rec.grad || ['#3a2f12', '#171821'];
  const ang = 115 + ((rec.seed || 1) * 23) % 60;

  return (
    <div style={{
      position: 'relative', width: '100%', aspectRatio: ratio, borderRadius: rounded,
      overflow: 'hidden', background: `linear-gradient(${ang}deg, ${a}, ${b})`,
      flex: 'none',
    }}>
      {isReal && !imgError && (
        <img 
          src={window.api.thumbURL(rec.id)} 
          loading="lazy" 
          onLoad={() => setImgLoaded(true)}
          onError={() => setImgError(true)}
          style={{
            position: 'absolute', inset: 0, width: '100%', height: '100%', 
            objectFit: 'contain', transition: 'opacity 0.25s ease-in-out',
            opacity: imgLoaded ? 1 : 0, zIndex: 2
          }}
        />
      )}

      {/* light sweep */}
      <div style={{ position: 'absolute', inset: 0, background:
        `radial-gradient(120% 80% at ${20 + (rec.seed || 1) * 13 % 60}% -10%, rgba(255,255,255,.16), transparent 55%)` }} />
      {/* faint stadium-floodlight streaks */}
      <div style={{ position: 'absolute', inset: 0, opacity: .5, background:
        `repeating-linear-gradient(${ang + 20}deg, transparent 0 22px, rgba(255,255,255,.025) 22px 23px)` }} />
      {/* subtle vignette + texture */}
      <div style={{ position: 'absolute', inset: 0, background:
        `radial-gradient(140% 120% at 50% 120%, rgba(0,0,0,.35), transparent 60%)` }} />
      {/* center glyph (placeholder shown only until the real image loads on top) */}
      <div style={{ position: 'absolute', inset: 0, display: 'grid', placeItems: 'center', color: 'rgba(255,255,255,.18)' }}>
        <Icon name="image" size={38} stroke={1.3} />
      </div>
    </div>
  );
}

function Spill({ dot, mono, children }) {
  return (
    <div className={'spill' + (mono ? ' mono' : '')}>
      {dot && <span className="dot" style={{ background: dot }} />}
      {children}
    </div>
  );
}

function Switch({ on, onClick }) {
  return <button className={'switch' + (on ? ' on' : '')} onClick={onClick} aria-pressed={on}><i /></button>;
}

function Check({ checked, onChange, label }) {
  return (
    <label className="check">
      <input type="checkbox" checked={checked} onChange={e => onChange(e.target.checked)} />
      <span className="box"><Icon name="check" size={12} stroke={2.6} /></span>
      {label}
    </label>
  );
}

/* Shared dropdown — a custom toggle listbox (replaces the native <select>, which can't
   be programmatically opened/closed). Same props + look as before, so it's a drop-in for
   the Library filters and the Edit-Tags scene dropdowns.
   - Click the field OR the caret to toggle open/closed.
   - Click outside, press Escape, or pick an option to close.
   - Keyboard: ↓ opens / moves down, ↑ moves up, Enter/Space opens or selects, Esc closes. */
function Sel({ value, onChange, options, allLabel }) {
  const [open, setOpen] = React.useState(false);
  const [hi, setHi] = React.useState(-1);
  const ref = React.useRef(null);

  const items = (allLabel ? [{ v: '', label: allLabel }] : []).concat((options || []).map(o => ({ v: o, label: o })));
  // Preserve a current value that isn't in the option list (legacy tag) so it stays shown.
  if (value && !items.some(it => it.v === value)) items.unshift({ v: value, label: value });
  const current = items.find(it => it.v === (value || '')) || items[0] || { v: '', label: allLabel || '' };

  React.useEffect(() => {
    if (!open) return;
    const onDoc = e => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, [open]);

  const choose = (v) => { onChange(v); setOpen(false); };
  const onKeyDown = (e) => {
    if (e.key === 'Escape') { if (open) { e.stopPropagation(); e.preventDefault(); setOpen(false); } return; }
    if (e.key === 'ArrowDown') { e.preventDefault(); if (!open) { setOpen(true); setHi(items.findIndex(it => it.v === (value || ''))); } else setHi(h => Math.min(h + 1, items.length - 1)); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); if (open) setHi(h => Math.max(h - 1, 0)); }
    else if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); if (!open) setOpen(true); else if (hi >= 0 && items[hi]) choose(items[hi].v); }
  };

  return (
    <div className="sel" ref={ref}>
      <button type="button" className="sel-trigger" aria-haspopup="listbox" aria-expanded={open}
        onClick={() => setOpen(o => !o)} onKeyDown={onKeyDown}>
        <span className="sel-val">{current.label}</span>
      </button>
      <span className="chev"><Icon name="chevDown" size={15} /></span>
      {open && (
        <div className="sel-pop" role="listbox">
          {items.map((it, i) => (
            <div key={it.v + '|' + i} role="option" aria-selected={it.v === (value || '')}
              className={'sel-opt' + (it.v === (value || '') ? ' on' : '') + (i === hi ? ' hi' : '')}
              onMouseEnter={() => setHi(i)}
              onMouseDown={(e) => { e.preventDefault(); choose(it.v); }}>
              {it.label}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* Multi-select dropdown — same look as <Sel>, but lets you pick several values.
   Clicking an option toggles it (popover stays open); caret/outside-click/Escape close. */
function MultiSel({ values, onChange, options, allLabel }) {
  const [open, setOpen] = React.useState(false);
  const ref = React.useRef(null);
  const vals = values || [];
  const sel = new Set(vals);

  React.useEffect(() => {
    if (!open) return;
    const onDoc = e => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, [open]);

  const toggle = (v) => onChange(sel.has(v) ? vals.filter(x => x !== v) : [...vals, v]);
  const onKeyDown = (e) => {
    if (e.key === 'Escape') { if (open) { e.stopPropagation(); e.preventDefault(); setOpen(false); } }
    else if (e.key === 'ArrowDown' || e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setOpen(o => !o); }
  };
  const label = vals.length === 0 ? (allLabel || 'All') : (vals.length === 1 ? vals[0] : `${vals.length} selected`);

  return (
    <div className="sel" ref={ref}>
      <button type="button" className="sel-trigger" aria-haspopup="listbox" aria-expanded={open}
        onClick={() => setOpen(o => !o)} onKeyDown={onKeyDown}>
        <span className="sel-val">{label}</span>
      </button>
      <span className="chev"><Icon name="chevDown" size={15} /></span>
      {open && (
        <div className="sel-pop" role="listbox" aria-multiselectable="true">
          {(options || []).length === 0 && <div className="sel-opt" style={{ color: 'var(--text-3)' }}>None available</div>}
          {(options || []).map(o => (
            <div key={o} role="option" aria-selected={sel.has(o)} className={'sel-opt' + (sel.has(o) ? ' on' : '')}
              onMouseDown={(e) => { e.preventDefault(); toggle(o); }}
              style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ width: 15, flex: 'none', display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}>
                {sel.has(o) && <Icon name="check" size={14} stroke={2.4} />}
              </span>
              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{o}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function Chip({ kind = 'tag', children, onRemove }) {
  return (
    <span className={'chip ' + kind}>
      {children}
      {onRemove && <span className="x" onClick={onRemove}><Icon name="close" size={11} stroke={2.2} /></span>}
    </span>
  );
}

function ConfBar({ v }) {
  const c = v >= 0.75 ? 'var(--ok)' : v >= 0.5 ? 'var(--warn)' : 'var(--danger)';
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 96 }}>
      <div style={{ flex: 1, height: 5, borderRadius: 999, background: 'var(--surface-3)', overflow: 'hidden' }}>
        <div style={{ width: (v * 100) + '%', height: '100%', background: c, borderRadius: 999 }} />
      </div>
      <span style={{ fontSize: 11, fontWeight: 650, color: c, fontVariantNumeric: 'tabular-nums', fontFamily: 'var(--font-mono)', width: 30 }}>
        {Math.round(v * 100)}
      </span>
    </div>
  );
}

/* ---- Appearance menu (theme + accent), surfaced in the top bar ---- */
function AppearanceMenu({ theme, accent, accents, onTheme, onAccent }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return;
    const h = e => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', h);
    return () => document.removeEventListener('mousedown', h);
  }, [open]);
  return (
    <div className="appearance" ref={ref}>
      <button className={'appr-btn' + (open ? ' open' : '')} onClick={() => setOpen(o => !o)}>
        <span className="appr-swatch" style={{ background: accents[accent].a }} />
        <Icon name={theme === 'light' ? 'sun' : 'moon'} size={15} />
        <span className="appr-label">Appearance</span>
        <Icon name="chevDown" size={14} />
      </button>
      {open && (
        <div className="appr-pop">
          <div className="appr-grp">Theme</div>
          <div className="appr-themes">
            {[['light', 'sun', 'Light'], ['dark', 'moon', 'Dark']].map(([v, ic, l]) => (
              <button key={v} className={'appr-theme' + (theme === v ? ' on' : '')} onClick={() => onTheme(v)}>
                <Icon name={ic} size={16} /> {l}
              </button>
            ))}
          </div>
          <div className="appr-grp">Accent colour</div>
          <div className="appr-accents">
            {Object.entries(accents).map(([name, c]) => (
              <button key={name} className={'appr-acc' + (accent === name ? ' on' : '')} onClick={() => onAccent(name)} title={name}>
                <span className="dot" style={{ background: c.a }}>{accent === name && <Icon name="check" size={12} stroke={3} style={{ color: c.on }} />}</span>
                <span>{name}</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/* ---- Title bar ---- */
function TitleBar({ screen }) {
  const names = { library: 'Library', tag: 'Tag photos', review: 'Review Tags', settings: 'Settings', collage: 'Collage Studio', favorites: 'Favourites' };
  // Brand logo: uses webui/logo.png if present; otherwise falls back to the
  // built-in mark + wordmark so the header never breaks if the file is missing.
  const [logoOk, setLogoOk] = React.useState(true);
  // No macOS "traffic-light" dots — this app ships on Windows and Mac, so the header
  // stays platform-neutral (the OS draws its own window controls).
  return (
    <div className="titlebar">
      <div className="brand">
        {logoOk ? (
          <img className="brand-logo" src="logo.png" alt="Super Search" onError={() => setLogoOk(false)} />
        ) : (
          <span className="mark"><Icon name="search" size={14} stroke={2.2} /></span>
        )}
        <span className="wordmark">Super Search Desktop</span>
      </div>
      <span className="sep" />
      <span className="crumb">{names[screen]}</span>
      <span className="spacer" />
    </div>
  );
}

/* ---- Sidebar ---- */
function Sidebar({ screen, setScreen, counts }) {
  // Settings removed for the client-facing prototype (Phase 1 freeze).
  const items = [
    { id: 'library', icon: 'library', label: 'Library', count: counts.library },
    { id: 'table', icon: 'grid', label: 'View Table' },
    { id: 'favorites', icon: 'star', label: 'Favourites', count: counts.favorites },
    { id: 'players', icon: 'faces', label: 'Player Management' },
    // { id: 'collage', icon: 'layers', label: 'Collage Studio' },
    { id: 'tag', icon: 'sparkles', label: 'Tag photos' },
    { id: 'review', icon: 'faces', label: 'Review Tags', count: counts.review },
  ];
  const pct = Math.round((counts.tagged / counts.total) * 100);
  return (
    <nav className="sidebar">
      <div className="nav-group-label">Workspace</div>
      {items.map(it => (
        <button key={it.id} className={'nav-item' + (screen === it.id ? ' active' : '')} onClick={() => setScreen(it.id)}>
          <Icon name={it.icon} size={18} />
          {it.label}
          {it.count != null && <span className="count">{it.count}</span>}
        </button>
      ))}
      <div className="grow" />
      <div className="side-card">
        <div className="row"><span>Photos tagged</span><b>{counts.tagged}/{counts.total}</b></div>
        <div className="bar"><i style={{ width: pct + '%' }} /></div>
        <div className="row"><span>Needs your review</span><b style={{ color: counts.review ? 'var(--warn)' : 'var(--text)' }}>{counts.review}</b></div>
      </div>
    </nav>
  );
}

Object.assign(window, { PhotoTile, Spill, Switch, Check, Sel, MultiSel, Chip, ConfBar, TitleBar, Sidebar, AppearanceMenu });
