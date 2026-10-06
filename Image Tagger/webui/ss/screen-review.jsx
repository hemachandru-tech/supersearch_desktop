/* Face Review Screen — human-in-the-loop validation queue grouped by picture.
   Spotlight design: the face being reviewed gets a bright, colour-configurable box with a
   label below it, while the rest of the photo is dimmed so the unknown person pops out.
   Other faces show as small dots you can click to jump to them (no clutter). Clicking the
   box opens the detail sidebar (accuracy + edit + save). */

const REVIEW_COLORS = [['#FFC72C', 'Yellow'], ['#34C98A', 'Green'], ['#F0626B', 'Red'], ['#4F8DF7', 'Blue']];

function _textOn(hex) {
  const c = hex.replace('#', '');
  const r = parseInt(c.substr(0, 2), 16), g = parseInt(c.substr(2, 2), 16), b = parseInt(c.substr(4, 2), 16);
  return (0.299 * r + 0.587 * g + 0.114 * b) > 140 ? '#10130a' : '#ffffff';
}

function ReviewScreen({ queue, onResolve, onOpenDetail }) {
  const D = window.SS_DATA;
  const [groupIdx, setGroupIdx] = React.useState(0);
  const [faceIdx, setFaceIdx] = React.useState(0);
  const [pick, setPick] = React.useState('');
  const [boxColor, setBoxColorState] = React.useState(() => localStorage.getItem('review_box_color') || '#FFC72C');
  const setBoxColor = (c) => { setBoxColorState(c); try { localStorage.setItem('review_box_color', c); } catch (e) {} };
  // Real pixel size of the loaded image — boxes are positioned against THIS so they line up
  // even when the database is missing the stored width/height.
  const [imgNat, setImgNat] = React.useState(null);

  // 1. Group the flat queue by image record ID
  const grouped = React.useMemo(() => {
    const map = new Map();
    queue.forEach(item => {
      if (!map.has(item.rec.id)) map.set(item.rec.id, { rec: item.rec, items: [] });
      map.get(item.rec.id).items.push(item);
    });
    return Array.from(map.values());
  }, [queue]);

  const curGroup = grouped[groupIdx];
  const curItem = curGroup ? curGroup.items[faceIdx] : null;

  React.useEffect(() => {
    if (grouped.length === 0) return;
    if (groupIdx >= grouped.length) { setGroupIdx(Math.max(0, grouped.length - 1)); setFaceIdx(0); }
    else if (curGroup && faceIdx >= curGroup.items.length) { setFaceIdx(Math.max(0, curGroup.items.length - 1)); }
  }, [grouped, groupIdx, faceIdx, curGroup]);

  React.useEffect(() => { setPick(curItem ? curItem.face.name : ''); }, [curItem]);
  // Forget the measured image size when we switch to a different photo.
  React.useEffect(() => { setImgNat(null); }, [curGroup && curGroup.rec.id]);

  // Move between IMAGES (review groups) — Prev/Next buttons + ← / → keyboard, mirroring
  // the Library viewer. Switching image resets to its first face.
  const gotoGroup = (delta) => {
    setGroupIdx(i => Math.max(0, Math.min(grouped.length - 1, i + delta)));
    setFaceIdx(0);
  };
  React.useEffect(() => {
    const onKey = e => {
      if (document.querySelector('.slideover')) return;            // detail viewer open over Review
      const tag = ((e.target && e.target.tagName) || '').toLowerCase();
      if (tag === 'input' || tag === 'textarea' || tag === 'select' || (e.target && e.target.isContentEditable)) return;
      if (e.key === 'ArrowLeft') { e.preventDefault(); gotoGroup(-1); }
      else if (e.key === 'ArrowRight') { e.preventDefault(); gotoGroup(1); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [grouped.length]);

  // Numeric box geometry (percent of the image's own pixels). Prefer the REAL loaded size
  // (naturalWidth/Height) over the DB's stored dims so boxes align even if dims are missing.
  function boxGeom(face) {
    if (!face || !face.bbox || !curGroup) return null;
    const [x1, y1, x2, y2] = face.bbox;
    if (x1 === 0 && y1 === 0 && x2 === 0 && y2 === 0) return null;
    const w = (imgNat && imgNat.w) || curGroup.rec.width || 1;
    const h = (imgNat && imgNat.h) || curGroup.rec.height || 1;
    const left = Math.max(0, Math.min(100, (x1 / w) * 100));
    const top = Math.max(0, Math.min(100, (y1 / h) * 100));
    const width = Math.max(0, Math.min(100 - left, ((x2 - x1) / w) * 100));
    const height = Math.max(0, Math.min(100 - top, ((y2 - y1) / h) * 100));
    return { left, top, width, height };
  }

  if (grouped.length === 0) {
    return (
      <div className="screen-pad">
        <div className="section-head" style={{ marginBottom: 18 }}><h1>Review tags</h1></div>
        <div className="empty" style={{ marginTop: 40 }}>
          <div className="empty-icon" style={{ color: 'var(--ok)' }}><Icon name="check" size={30} stroke={2} /></div>
          <h3>All caught up</h3>
          <p>Every detected face has been confirmed. New low-confidence predictions will appear here for a quick yes/no.</p>
        </div>
      </div>
    );
  }

  function resolve(action, name) {
    if (!curItem) return;
    onResolve(curItem, action, name);
    if (curGroup.items.length <= 1) {
      if (groupIdx >= grouped.length - 1) setGroupIdx(Math.max(0, groupIdx - 1));
      setFaceIdx(0);
    } else if (faceIdx >= curGroup.items.length - 1) {
      setFaceIdx(Math.max(0, faceIdx - 1));
    }
  }

  const openDetail = () => { if (onOpenDetail && curGroup) onOpenDetail(curGroup.rec); };
  const g = curItem ? boxGeom(curItem.face) : null;
  const isUnknown = curItem && curItem.face.name === 'Unknown';
  const labelText = curItem ? (isUnknown ? 'Unknown — tap to identify' : `${curItem.face.name} · ${Math.round(curItem.face.conf * 100)}%`) : '';

  return (
    <div className="screen-pad" style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div className="section-head" style={{ marginBottom: 16 }}>
        <h1>Review tags</h1>
        <span className="sub">We box the exact face we're unsure about — confirm who it is, or open it for full details.</span>
        <span style={{ flex: 1 }} />
        {/* Previous / Next image navigation (← / →) */}
        {grouped.length > 1 && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginRight: 14 }}>
            <button className="btn ghost icon sm" onClick={() => gotoGroup(-1)} disabled={groupIdx === 0} title="Previous image (←)"><Icon name="chevLeft" size={18} /></button>
            <span style={{ fontSize: 12, color: 'var(--text-3)', fontVariantNumeric: 'tabular-nums', minWidth: 54, textAlign: 'center' }}>{groupIdx + 1} / {grouped.length}</span>
            <button className="btn ghost icon sm" onClick={() => gotoGroup(1)} disabled={groupIdx >= grouped.length - 1} title="Next image (→)"><Icon name="chevRight" size={18} /></button>
          </div>
        )}
        {/* Box colour picker */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginRight: 14 }}>
          <span style={{ fontSize: 11.5, color: 'var(--text-3)', fontWeight: 600 }}>Box colour</span>
          {REVIEW_COLORS.map(([c, name]) => (
            <button key={c} title={name} onClick={() => setBoxColor(c)}
              style={{ width: 20, height: 20, borderRadius: '50%', background: c, cursor: 'pointer', padding: 0,
                       border: boxColor === c ? '2px solid var(--text)' : '2px solid var(--line)', outline: 'none' }} />
          ))}
        </div>
        <Spill dot="var(--warn)"><b>{grouped.length}</b> files need review</Spill>
      </div>

      <div className="review-layout">
        {/* Sidebar: Grouped Image List */}
        <div className="rev-queue">
          {grouped.map((gp, n) => (
            <button key={gp.rec.id} className={'rq-item' + (n === groupIdx ? ' active' : '')} onClick={() => { setGroupIdx(n); setFaceIdx(0); }}>
              <div className="rq-thumb"><PhotoTile rec={gp.rec} ratio="1 / 1" rounded={6} /></div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div className="rq-name">{gp.rec.file}</div>
                <div className="rq-file">{gp.rec.tournament || 'Unknown Tournament'}</div>
              </div>
              <span className="count-badge" style={{ background: 'var(--warn-soft)', color: 'var(--warn)', padding: '2px 6px', borderRadius: 4, fontSize: 11, fontWeight: 700, flex: 'none', marginLeft: 8 }}>
                {gp.items.length}
              </span>
            </button>
          ))}
        </div>

        {/* Main Panel: Interactive Canvas & Review Details */}
        {curItem && (
          <div className="rev-main">
            {/* Left: the actual image with a SPOTLIGHT on the face under review */}
            <div className="rev-photo">
              <div className="rev-canvas" style={{ position: 'relative', width: '100%', borderRadius: 14, overflow: 'hidden', background: '#0c0d12' }}>
                <img src={'/api/file?id=' + encodeURIComponent(curGroup.rec.id)} alt={curGroup.rec.file}
                     onLoad={e => setImgNat({ w: e.target.naturalWidth, h: e.target.naturalHeight })}
                     onError={e => { if (!e.currentTarget.dataset.fb) { e.currentTarget.dataset.fb = '1'; e.currentTarget.src = window.api.thumbURL(curGroup.rec.id); } }}
                     style={{ display: 'block', width: '100%', height: 'auto' }} />

                {/* Other faces: small dots; click to spotlight them (keeps the view uncluttered) */}
                {curGroup.items.map((item, m) => {
                  if (m === faceIdx) return null;
                  const og = boxGeom(item.face);
                  if (!og) return null;
                  return (
                    <button key={item.fi} onClick={() => setFaceIdx(m)} title={`Review: ${item.face.name}`}
                      style={{ position: 'absolute', left: `${og.left + og.width / 2}%`, top: `${og.top + og.height / 2}%`,
                               transform: 'translate(-50%,-50%)', width: 16, height: 16, borderRadius: '50%', padding: 0,
                               background: 'rgba(255,255,255,0.9)', border: `2px solid ${boxColor}`,
                               boxShadow: '0 1px 5px rgba(0,0,0,0.55)', cursor: 'pointer', zIndex: 12 }} />
                  );
                })}

                {/* Active face: bright box + spotlight (dims everything else) + label BELOW */}
                {g && (
                  <React.Fragment>
                    <div onClick={openDetail} title="Open details & accuracy"
                      style={{ position: 'absolute', left: `${g.left}%`, top: `${g.top}%`, width: `${g.width}%`, height: `${g.height}%`,
                               border: `3px solid ${boxColor}`, borderRadius: 6, cursor: 'pointer', zIndex: 10,
                               boxShadow: `0 0 0 9999px rgba(8,9,12,0.62), 0 0 16px ${boxColor}` }} />
                    <div onClick={openDetail}
                      style={{ position: 'absolute', left: `${g.left}%`, top: `${g.top + g.height}%`, transform: 'translateY(7px)',
                               background: boxColor, color: _textOn(boxColor), fontWeight: 800, fontSize: 12, padding: '4px 9px',
                               borderRadius: 7, whiteSpace: 'nowrap', maxWidth: '94%', overflow: 'hidden', textOverflow: 'ellipsis',
                               boxShadow: '0 2px 8px rgba(0,0,0,0.45)', cursor: 'pointer', zIndex: 13 }}>
                      {labelText}
                    </div>
                  </React.Fragment>
                )}

                {/* If the active face has no stored box, tell the user (older records) */}
                {!g && (
                  <div style={{ position: 'absolute', left: 12, bottom: 12, background: 'rgba(0,0,0,0.6)', color: '#fff',
                                fontSize: 12, padding: '6px 10px', borderRadius: 6, zIndex: 13 }}>
                    No saved face box for this one — re-tag this folder to capture it.
                  </div>
                )}
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 8 }}>
                <code className="rev-file">{curGroup.rec.file}</code>
                <span style={{ flex: 1 }} />
                <button className="btn ghost sm" onClick={openDetail}><Icon name="external" size={14} /> Open details &amp; accuracy</button>
              </div>
            </div>

            {/* Right: details & manual resolution */}
            <div className="rev-panel">
              <div style={{ marginBottom: 16 }}>
                <span className="rev-q-label">Faces in this photo ({curGroup.items.length})</span>
                <div style={{ display: 'flex', gap: 8, marginTop: 8, overflowX: 'auto', paddingBottom: 4 }}>
                  {curGroup.items.map((item, m) => (
                    <button key={item.fi} onClick={() => setFaceIdx(m)}
                      style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '6px 10px', borderRadius: 6,
                               background: m === faceIdx ? 'var(--accent-soft)' : 'var(--surface-3)',
                               border: `1px solid ${m === faceIdx ? 'var(--accent)' : 'var(--line)'}`,
                               color: m === faceIdx ? 'var(--text)' : 'var(--text-2)', cursor: 'pointer',
                               whiteSpace: 'nowrap', fontSize: 12.5, fontWeight: 600 }}>
                      <span style={{ width: 8, height: 8, borderRadius: '50%', background: m === faceIdx ? boxColor : 'var(--text-3)' }} />
                      <span>{item.face.name} ({Math.round(item.face.conf * 100)}%)</span>
                    </button>
                  ))}
                </div>
              </div>

              {isUnknown && (
                <div style={{ background: 'rgba(240, 169, 59, 0.08)', border: '1px solid rgba(240, 169, 59, 0.25)', borderRadius: 8, padding: '12px 14px', marginBottom: 18, fontSize: 12, color: '#F8C377', lineHeight: 1.5 }}>
                  <div style={{ fontWeight: 700, display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4, fontSize: 12.5 }}>
                    <Icon name="alert" size={14} /><span>Identity Unknown</span>
                  </div>
                  This face didn't match any known player closely enough (its similarity to every player's
                  reference photos was below the match threshold), so we left it for you. Pick the right name below.
                </div>
              )}

              <div className="rev-q">
                <span className="rev-q-label">We think this is</span>
                <div className="rev-pred">{curItem.face.name}</div>
                <ConfBar v={curItem.face.conf} />
                <div style={{ fontSize: 12.5, color: 'var(--text-3)', lineHeight: 1.4, marginTop: 10, fontStyle: 'italic' }}>
                  {isUnknown ? (
                    <span><strong>Why:</strong> the facial features didn't match any player closely enough ({Math.round(curItem.face.conf * 100)}% best match — below the strictness setting). Lower "Face match strictness" in Settings to catch more, or tag the right name below.</span>
                  ) : (
                    <span><strong>Why:</strong> the facial features are {Math.round(curItem.face.conf * 100)}% similar to <strong>{curItem.face.name}</strong>'s reference photos, but below the auto-confirm level — please confirm.</span>
                  )}
                </div>
              </div>

              <div className="rev-pick">
                <span className="md-label" style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', color: 'var(--text-3)' }}>Correct name</span>
                <div className="sel" style={{ width: '100%' }}>
                  <select value={pick} onChange={e => setPick(e.target.value)} style={{ width: '100%', height: 42 }}>
                    {!D.ROSTER.includes(curItem.face.name) && curItem.face.name !== 'Unknown' && <option value={curItem.face.name}>{curItem.face.name}</option>}
                    {D.ROSTER.map(r => <option key={r} value={r}>{r}</option>)}
                    <option value="Unknown">Unknown / not a player</option>
                  </select>
                  <span className="chev"><Icon name="chevDown" size={15} /></span>
                </div>
              </div>

              <div className="rev-actions">
                {curItem.face.name !== 'Unknown' && (
                  <button className="btn primary" onClick={() => resolve('confirm', curItem.face.name)}>
                    <Icon name="check" size={16} stroke={2.4} /> Confirm “{curItem.face.name}”
                  </button>
                )}
                <button className="btn primary" disabled={pick === curItem.face.name || pick === 'Unknown'} onClick={() => resolve('correct', pick)}>
                  <Icon name="edit" size={15} /> Save as “{pick}”
                </button>
                <button className="btn ghost" onClick={() => resolve('reject', 'Unknown')} style={{ color: 'var(--danger)' }}>
                  <Icon name="close" size={16} /> Not a player
                </button>
              </div>

              <div className="rev-layers">
                <div className="rev-q-label" style={{ marginBottom: 8, display: 'block' }}>How we decided</div>
                <div className="rl-row">
                  <span className={`rl-dot ${!isUnknown ? 'pass' : 'warn'}`} />
                  <span className="rl-t">Facial-feature match</span>
                  <span className="rl-d">{Math.round(curItem.face.conf * 100)}% similar</span>
                </div>
                <div className="rl-row">
                  <span className={`rl-dot ${!isUnknown ? 'pass' : 'fail'}`} />
                  <span className="rl-t">Open-set check</span>
                  <span className="rl-d">{!isUnknown ? 'Matched a known player' : 'No confident match'}</span>
                </div>
                <div className="rl-row">
                  <span className={`rl-dot ${curItem.face.status === 'confirmed' ? 'pass' : 'warn'}`} />
                  <span className="rl-t">Status</span>
                  <span className="rl-d">{curItem.face.status === 'confirmed' ? 'Human verified' : 'Needs review'}</span>
                </div>
              </div>

              <p className="rev-hint" style={{ marginTop: 14 }}><Icon name="info" size={13} /> Your choice updates this photo's tags and is embedded into the file.</p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

window.ReviewScreen = ReviewScreen;
