/* Image detail slide-over — editable metadata, face panel, EXIF mapping, actions */

function Field({ label, value, onChange, mono, textarea }) {
  return (
    <label className="md-field">
      <span className="md-label">{label}</span>
      {textarea
        ? <textarea className="input" value={value} onChange={e => onChange(e.target.value)} rows={3} />
        : <input className="input" value={value} onChange={e => onChange(e.target.value)}
            style={mono ? { fontFamily: 'var(--font-mono)', fontSize: 12.5 } : null} />}
    </label>
  );
}

/* Controlled-vocabulary editor (Event/Mood/Action/Location/Jersey type).
   Reuses the shared <Sel> dropdown. If the saved value isn't in the canonical
   list (e.g. legacy free-text from an older tag run), it's prepended so the
   existing value is preserved and visible until the user picks a canonical one. */
function SelectField({ label, value, onChange, options }) {
  const opts = (value && !options.includes(value)) ? [value, ...options] : options;
  return (
    <label className="md-field">
      <span className="md-label">{label}</span>
      <Sel value={value || ''} onChange={onChange} options={opts} allLabel="—" />
    </label>
  );
}

/* Searchable multi-player selector (chips + type-ahead) for the Player(s) field.
   - Roster source: window.SS_DATA.ROSTER (from /api/filters.players => the trained
     face model's label_encoder.classes_). No new source, no new table.
   - Multi-value: serialises selected players back to the SAME comma-separated
     string the field has always used (`value`/`onChange` are draft.playersStr),
     so the save payload (player_names) and backend faces_json sync are unchanged.
   - Legacy / off-roster names: typing a name and pressing Enter keeps it as a chip
     (flagged, never dropped), so existing values remain visible and editable. */
function PlayerPicker({ value, onChange, roster }) {
  const list = roster || [];
  const players = React.useMemo(
    () => (value || '').split(',').map(s => s.trim()).filter(Boolean),
    [value]
  );
  const [query, setQuery] = React.useState('');
  const [open, setOpen] = React.useState(false);
  const [hi, setHi] = React.useState(0);
  const boxRef = React.useRef(null);

  const commit = (arr) => {
    const seen = new Set(), out = [];
    arr.forEach(n => { const k = n.toLowerCase(); if (n && !seen.has(k)) { seen.add(k); out.push(n); } });
    onChange(out.join(', '));
  };
  const add = (name) => { const n = (name || '').trim(); if (!n) return; commit([...players, n]); setQuery(''); setHi(0); };
  const remove = (name) => commit(players.filter(p => p !== name));

  const selected = new Set(players.map(p => p.toLowerCase()));
  const suggestions = React.useMemo(() => {
    const q = query.trim().toLowerCase();
    return list
      .filter(r => !selected.has(r.toLowerCase()))
      .filter(r => !q || r.toLowerCase().includes(q))
      .slice(0, 8);
  }, [query, value, roster]);

  React.useEffect(() => {
    if (!open) return;
    const h = e => { if (boxRef.current && !boxRef.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', h);
    return () => document.removeEventListener('mousedown', h);
  }, [open]);

  const onKeyDown = (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      if (open && suggestions[hi]) add(suggestions[hi]);
      else if (query.trim()) add(query);          // free-text / legacy name
    } else if (e.key === 'ArrowDown') {
      e.preventDefault(); setOpen(true); setHi(h => Math.min(h + 1, Math.max(suggestions.length - 1, 0)));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault(); setHi(h => Math.max(h - 1, 0));
    } else if (e.key === 'Backspace' && !query && players.length) {
      remove(players[players.length - 1]);
    } else if (e.key === 'Escape') {
      setOpen(false);
    }
  };

  return (
    <label className="md-field" style={{ position: 'relative' }}>
      <span className="md-label">Player(s)</span>
      <div className="input" ref={boxRef} onClick={() => setOpen(true)}
        style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center', height: 'auto', minHeight: 42, padding: '7px 10px', cursor: 'text' }}>
        {players.map(p => {
          const known = list.some(r => r.toLowerCase() === p.toLowerCase());
          return (
            <span key={p} title={known ? '' : 'Not in roster — legacy value, preserved'}
              style={{ display: 'inline-flex', alignItems: 'center', gap: 5, padding: '3px 5px 3px 9px', borderRadius: 999, fontSize: 12.5, fontWeight: 600, background: 'var(--accent-soft)', border: '1px solid var(--accent-line)' }}>
              {!known && <Icon name="alert" size={11} style={{ color: 'var(--warn)' }} />}
              {p}
              <span onClick={e => { e.stopPropagation(); remove(p); }} style={{ cursor: 'pointer', display: 'inline-flex', opacity: 0.65 }}>
                <Icon name="close" size={11} stroke={2.2} />
              </span>
            </span>
          );
        })}
        <input value={query}
          onChange={e => { setQuery(e.target.value); setOpen(true); setHi(0); }}
          onFocus={() => setOpen(true)}
          onKeyDown={onKeyDown}
          placeholder={players.length ? 'Add player…' : 'Search roster or type a name…'}
          style={{ flex: 1, minWidth: 130, border: 'none', outline: 'none', background: 'transparent', color: 'inherit', fontSize: 13.5, padding: '2px 0' }} />
        {/* caret toggle — click to open/close the suggestions list */}
        <button type="button" tabIndex={-1} title={open ? 'Close suggestions' : 'Show players'}
          onClick={e => { e.stopPropagation(); setOpen(o => !o); }}
          style={{ marginLeft: 'auto', border: 'none', background: 'transparent', color: 'var(--text-3)', cursor: 'pointer', display: 'inline-flex', alignItems: 'center', padding: 2, alignSelf: 'center', transition: 'transform .15s var(--ease)', transform: open ? 'rotate(180deg)' : 'none' }}>
          <Icon name="chevDown" size={15} />
        </button>
      </div>
      {open && suggestions.length > 0 && (
        <div style={{ position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 50, marginTop: 4, background: 'var(--surface)', border: '1px solid var(--line)', borderRadius: 10, boxShadow: '0 10px 30px rgba(0,0,0,0.25)', maxHeight: 240, overflowY: 'auto', padding: 4 }}>
          {suggestions.map((s, i) => (
            <div key={s} onMouseDown={e => { e.preventDefault(); add(s); }} onMouseEnter={() => setHi(i)}
              style={{ padding: '8px 10px', borderRadius: 7, cursor: 'pointer', fontSize: 13, background: i === hi ? 'var(--surface-2)' : 'transparent' }}>
              {s}
            </div>
          ))}
        </div>
      )}
    </label>
  );
}

function DetailPanel({ rec, onClose, onSave, onStar, onPrev, onNext, hasPrev, hasNext, navPos, navCount }) {
  const D = window.SS_DATA;
  const [draft, setDraft] = useState(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [tab, setTab] = useState('meta');
  const [lightbox, setLightbox] = useState(false);

  useEffect(() => {
    if (rec) {
      setDraft({ ...rec, playersStr: rec.players.join(', ') });
      setSaved(false);
      // tab + lightbox (zoom) are intentionally PRESERVED across Prev/Next navigation;
      // they reset naturally on a fresh open because the panel unmounts when closed.
    }
  }, [rec]);

  // Keyboard: ← Prev, → Next, Esc close. Active only while the viewer is mounted, and
  // never while a text/edit control is focused (so editing fields isn't disrupted).
  useEffect(() => {
    const onKey = e => {
      const el = e.target;
      const tag = ((el && el.tagName) || '').toLowerCase();
      const typing = tag === 'input' || tag === 'textarea' || tag === 'select'
        || (el && el.isContentEditable) || (el && el.closest && el.closest('.md-field'));
      if (e.key === 'Escape') { if (lightbox) setLightbox(false); else onClose && onClose(); return; }
      if (typing) return;
      if (e.key === 'ArrowLeft') { e.preventDefault(); if (hasPrev && onPrev) onPrev(); }
      else if (e.key === 'ArrowRight') { e.preventDefault(); if (hasNext && onNext) onNext(); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [lightbox, onClose, onPrev, onNext, hasPrev, hasNext]);

  if (!rec || !draft) return null;
  const set = (k, v) => setDraft(d => ({ ...d, [k]: v }));
  const dirty = JSON.stringify({ ...rec, playersStr: rec.players.join(', ') }) !== JSON.stringify(draft);

  // ---- Accuracy = FACE-RECOGNITION certainty ONLY (not metadata completeness) ----
  // The score answers one question: "how sure are we about WHO this player is, from the
  // face alone?" Other tags (event, mood, jersey…) deliberately do NOT affect it.
  const faces = rec.faces || [];
  const namedFaces = faces.filter(f => f && f.name && f.name !== 'Unknown');
  const reviewFaces = faces.filter(f => f && (!f.name || f.name === 'Unknown' || f.status === 'review'));
  const avgConf = namedFaces.length
    ? namedFaces.reduce((s, f) => s + (f.conf || 0), 0) / namedFaces.length
    : 0;
  const accuracyScore = Math.round(avgConf * 100);
  const scoreTone = namedFaces.length === 0 ? 'var(--text-3)'
    : accuracyScore >= 75 ? 'var(--ok)' : accuracyScore >= 50 ? 'var(--warn)' : 'var(--danger)';
  // Plain-English doubts, in the spirit of "I have these reservations but still think it's them".
  const grievances = [];
  namedFaces.filter(f => (f.conf || 0) < 0.6).forEach(f =>
    grievances.push(`${f.name}: features are partially ambiguous (angle / blur / lighting) — only ${Math.round((f.conf || 0) * 100)}% sure`));
  if (reviewFaces.length)
    grievances.push(`${reviewFaces.length} detected face${reviewFaces.length > 1 ? 's' : ''} couldn't be confidently matched — sent to Review`);
  const verdict = namedFaces.length === 0
    ? 'No detected face was confidently matched to a known player.'
    : accuracyScore >= 75
      ? `Strong facial-feature match — confident about ${namedFaces.length === 1 ? 'this player' : 'these players'}.`
      : `Likely ${namedFaces.map(f => f.name).join(', ')}, but only ${accuracyScore}% sure from the face alone.`;

  async function save() {
    setSaving(true);
    try {
      const payload = {
        player_names: draft.playersStr,
        event_type: draft.event,
        mood: draft.mood,
        action: draft.action,
        location: draft.location,
        jersey_color: draft.jersey,
        apparel: draft.apparel,
        crowd_present: draft.crowd,
        caption: draft.caption,
        tournament: draft.tournament
      };
      
      const res = await window.api.save(rec.id, payload);
      setSaving(false); 
      setSaved(true);
      
      onSave({ 
        ...draft, 
        players: draft.playersStr.split(',').map(s => s.trim()).filter(Boolean),
        embedded: res.image ? res.image.metadata_written === 1 : true
      });
      
      setTimeout(() => setSaved(false), 2200);
    } catch(err) {
      alert("Failed to save changes: " + err.message);
      setSaving(false);
    }
  }

  async function verifyMetadata() {
    setVerifying(true);
    try {
      const res = await window.api.verify(rec.id);
      if (res.ok) {
        const metadataInfo = Object.entries(res.embedded || {})
          .map(([k, v]) => `${k}: ${v}`)
          .join('\n');
        alert("Metadata successfully verified on disk!\n\n" + (metadataInfo || "No embedded tags found."));
      } else {
        alert("Verification failed: " + res.error);
      }
    } catch (err) {
      alert("Verification error: " + err.message);
    } finally {
      setVerifying(false);
    }
  }

  return (
    <div className="overlay" onMouseDown={onClose}>
      <aside className="slideover" onMouseDown={e => e.stopPropagation()}>
        {/* header */}
        <div className="so-head">
          <span className={'badge ' + rec.format}>{rec.format}</span>
          <div style={{ display: 'flex', flexDirection: 'column', flexShrink: 1, paddingRight: 8 }}>
            <code className="so-path" style={{ whiteSpace: 'normal', wordBreak: 'break-all', overflow: 'visible' }} title={rec.file}>{rec.file}</code>
            {rec.folder && <code className="so-path" style={{ whiteSpace: 'normal', wordBreak: 'break-all', overflow: 'visible', color: 'var(--text-3)', fontSize: 11, marginTop: 2, userSelect: 'all' }} title={rec.folder}>{rec.folder}</code>}
          </div>
          <span style={{ flex: 1 }} />
          {navCount > 1 && (
            <>
              <button className="btn ghost icon sm" onClick={onPrev} disabled={!hasPrev} title="Previous (←)">
                <Icon name="chevLeft" size={18} />
              </button>
              <span style={{ fontSize: 12, color: 'var(--text-3)', fontVariantNumeric: 'tabular-nums', minWidth: 56, textAlign: 'center' }}>
                {navPos} / {navCount}
              </span>
              <button className="btn ghost icon sm" onClick={onNext} disabled={!hasNext} title="Next (→)">
                <Icon name="chevRight" size={18} />
              </button>
              <span style={{ width: 1, height: 18, background: 'var(--line-strong)', margin: '0 4px' }} />
            </>
          )}
          <button className={'btn ghost icon sm' + (rec.starred ? '' : '')} onClick={() => onStar(rec.id)} title="Star">
            <Icon name="star" size={16} fill={rec.starred} style={{ color: rec.starred ? 'var(--accent)' : 'inherit' }} />
          </button>
          <button className="btn ghost icon sm" onClick={onClose} title="Close (Esc)"><Icon name="close" size={17} /></button>
        </div>

        <div className="so-body">
          {/* preview (click to open full image in-app). Uses the full-image endpoint
              (reliable on Windows), falling back to the thumbnail if it can't load. */}
          <div className="so-preview" onClick={() => setLightbox(true)} style={{ cursor: 'zoom-in' }} title="Click to view full image">
            <img
              src={'/api/file?id=' + encodeURIComponent(rec.id)}
              alt={rec.file}
              onError={e => { if (!e.currentTarget.dataset.fb) { e.currentTarget.dataset.fb = '1'; e.currentTarget.src = window.api.thumbURL(rec.id); } }}
              style={{ display: 'block', width: '100%', height: 'auto', maxHeight: '46vh', objectFit: 'contain', borderRadius: 14, background: '#0c0d12' }}
            />
            <div className="so-exif-row">
              <span><Icon name="image" size={13} /> {rec.dims || 'Unknown'}</span>
              <span>{rec.size || ''}</span>
              <span className={rec.embedded ? 'ok' : 'warn'}>
                <Icon name={rec.embedded ? 'check' : 'alert'} size={13} /> {rec.embedded ? 'Tagged' : 'Not tagged yet'}
              </span>
            </div>
          </div>

          {/* tabs */}
          <div className="so-tabs">
            {[['meta', 'Details'], ['faces', `People · ${rec.faces.length}`]].map(([v, l]) => (
              <button key={v} className={tab === v ? 'on' : ''} onClick={() => setTab(v)}>{l}</button>
            ))}
          </div>

          {tab === 'meta' && (
            <div className="md-grid">
              {/* Face Match Confidence — driven only by face-recognition certainty */}
              <div style={{
                background: 'var(--surface-2)',
                border: '1px solid var(--line)',
                borderRadius: 10,
                padding: '14px 16px',
                marginBottom: 16,
                gridColumn: '1 / -1'
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                  <span style={{ fontSize: 13, fontWeight: 700, display: 'flex', alignItems: 'center', gap: 6 }}>
                    <Icon name="faces" size={14} style={{ color: 'var(--accent)' }} />
                    Face Match Confidence
                  </span>
                  <span style={{ fontSize: 14, fontWeight: 800, color: scoreTone }}>
                    {namedFaces.length === 0 ? '—' : `${accuracyScore}%`}
                  </span>
                </div>

                {/* Confidence bar */}
                <div style={{ width: '100%', height: 6, borderRadius: 3, background: 'var(--surface-3)', overflow: 'hidden', marginBottom: 12 }}>
                  <div style={{ width: `${accuracyScore}%`, height: '100%', background: scoreTone, transition: 'width 0.3s ease' }} />
                </div>

                {/* Per-player certainty */}
                {namedFaces.length > 0 && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 8 }}>
                    {namedFaces.map((f, i) => (
                      <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 12 }}>
                        <span style={{ minWidth: 120, fontWeight: 600 }}>{f.name}</span>
                        <ConfBar v={f.conf || 0} />
                      </div>
                    ))}
                  </div>
                )}

                {/* Verdict + plain-English doubts */}
                <div style={{ fontSize: 11.5, color: 'var(--text-2)', lineHeight: 1.5 }}>
                  <div style={{ display: 'flex', alignItems: 'flex-start', gap: 5, color: scoreTone, fontWeight: 600 }}>
                    <Icon name={accuracyScore >= 75 ? 'check' : 'alert'} size={12} style={{ marginTop: 2, flexShrink: 0 }} />
                    <span>{verdict}</span>
                  </div>
                  {grievances.length > 0 && (
                    <ul style={{ margin: '6px 0 0', paddingLeft: 18, display: 'flex', flexDirection: 'column', gap: 3 }}>
                      {grievances.map((g, i) => <li key={i}>{g}</li>)}
                    </ul>
                  )}
                </div>
              </div>

              <PlayerPicker value={draft.playersStr} onChange={v => set('playersStr', v)} roster={D.ROSTER || []} />
              <div className="md-two">
                <SelectField label="Event" value={draft.event} onChange={v => set('event', v)} options={D.EVENTS} />
                <SelectField label="Mood" value={draft.mood} onChange={v => set('mood', v)} options={D.MOODS} />
              </div>
              <div className="md-two">
                <SelectField label="Action" value={draft.action} onChange={v => set('action', v)} options={D.ACTIONS} />
                <SelectField label="Location" value={draft.location} onChange={v => set('location', v)} options={D.LOCATIONS} />
              </div>
              <div className="md-two">
                <Field label="Jersey colour" value={draft.jersey} onChange={v => set('jersey', v)} />
                <SelectField label="Jersey type" value={draft.apparel} onChange={v => set('apparel', v)} options={D.JERSEY_TYPES} />
              </div>
              <div className="md-two">
                <Field label="Crowd present" value={draft.crowd} onChange={v => set('crowd', v)} />
                <Field label="Tournament" value={draft.tournament} onChange={v => set('tournament', v)} />
              </div>
              <Field label="Caption" value={draft.caption} onChange={v => set('caption', v)} textarea />
            </div>
          )}

          {tab === 'faces' && (
            <div className="faces-list">
              {rec.faces.length === 0 && (
                <div className="faces-empty"><Icon name="faces" size={26} stroke={1.4} /><p>No faces detected in this image.</p></div>
              )}
              {rec.faces.map((f, i) => (
                <div key={i} className="face-row" style={{ display: 'flex', flexDirection: 'column', gap: 8, padding: '12px 14px', borderBottom: '1px solid var(--line)' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 12, width: '100%' }}>
                    <div className="face-thumb"><Icon name="faces" size={20} /></div>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div className="face-name">{f.name}</div>
                      <ConfBar v={f.conf} />
                    </div>
                    <span className={'face-status ' + f.status}>
                      {f.status === 'confirmed' ? 'Confirmed' : f.status === 'review' ? 'Needs review' : 'Not a player'}
                    </span>
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--text-3)', lineHeight: 1.4, paddingLeft: 32, fontStyle: 'italic' }}>
                    {f.name === 'Unknown' ? (
                      <span><strong>Reason:</strong> Face features did not confidently match any of the 42 trained roster profiles. The confidence score of {Math.round(f.conf * 100)}% was below the SVM threshold or consensus boundary. This can happen due to profile tilt, lighting, or the person not being in the trained database.</span>
                    ) : (
                      <span><strong>Reason:</strong> Confirmed as {f.name} based on matching facial geometry to the 42-player roster. Embedding vector shows high similarity with {Math.round(f.conf * 100)}% confidence, cross-validated by Support Vector Machine (SVM) and consensus models.</span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* footer */}
        <div className="so-foot">
          <button className="btn primary" onClick={save} disabled={saving || (!dirty && !saved)}>
            {saving ? <><span className="spin" /> Saving…</> : saved ? <><Icon name="check" size={16} stroke={2.4} /> Saved</> : <><Icon name="save" size={16} /> Save changes</>}
          </button>
          <button className="btn ghost" onClick={verifyMetadata} disabled={verifying} style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
            {verifying ? <><span className="spin" /> Verifying…</> : <><Icon name="check" size={15} /> Verify Metadata</>}
          </button>
          <button className="btn ghost icon" title="Open full image" onClick={() => setLightbox(true)}><Icon name="external" size={17} /></button>
        </div>
      </aside>

      {/* Full-image lightbox — opens inside the app (click anywhere or press Esc to close) */}
      {lightbox && (
        <div
          onMouseDown={e => { e.stopPropagation(); setLightbox(false); }}
          style={{
            position: 'fixed', inset: 0, zIndex: 1000, background: 'rgba(8,9,12,0.92)',
            display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'zoom-out',
            backdropFilter: 'blur(4px)'
          }}
        >
          <img
            src={'/api/file?id=' + encodeURIComponent(rec.id)}
            alt={rec.file}
            onMouseDown={e => e.stopPropagation()}
            style={{ maxWidth: '94vw', maxHeight: '92vh', objectFit: 'contain', borderRadius: 8, boxShadow: '0 20px 80px rgba(0,0,0,0.6)' }}
          />
          {/* Prev/Next arrows inside fullscreen — keep zoom/fullscreen state across navigation */}
          {navCount > 1 && hasPrev && (
            <button className="btn ghost icon" title="Previous (←)"
              onMouseDown={e => { e.stopPropagation(); onPrev && onPrev(); }}
              style={{ position: 'fixed', left: 18, top: '50%', transform: 'translateY(-50%)', background: 'rgba(0,0,0,0.45)', color: '#fff', width: 44, height: 44 }}>
              <Icon name="chevLeft" size={24} />
            </button>
          )}
          {navCount > 1 && hasNext && (
            <button className="btn ghost icon" title="Next (→)"
              onMouseDown={e => { e.stopPropagation(); onNext && onNext(); }}
              style={{ position: 'fixed', right: 18, top: '50%', transform: 'translateY(-50%)', background: 'rgba(0,0,0,0.45)', color: '#fff', width: 44, height: 44 }}>
              <Icon name="chevRight" size={24} />
            </button>
          )}
          <button
            className="btn ghost icon"
            onMouseDown={e => { e.stopPropagation(); setLightbox(false); }}
            title="Close (Esc)"
            style={{ position: 'fixed', top: 18, right: 18, background: 'rgba(0,0,0,0.4)', color: '#fff' }}
          >
            <Icon name="close" size={22} />
          </button>
          <div style={{ position: 'fixed', bottom: 16, left: '50%', transform: 'translateX(-50%)', display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
            <code style={{ color: 'rgba(255,255,255,0.7)', fontSize: 12, fontFamily: 'var(--font-mono)' }}>{rec.file}</code>
            {rec.folder && <code style={{ color: 'rgba(255,255,255,0.4)', fontSize: 11, fontFamily: 'var(--font-mono)', marginTop: 2 }}>{rec.folder}</code>}
          </div>
        </div>
      )}
    </div>
  );
}

Object.assign(window, { DetailPanel });

