/* Library / Search screen + Image detail slide-over */

function FilterDropdowns({ filters, setFilter, D }) {
  // Library filters show ONLY values present in currently-tagged content (D.LIB,
  // populated from /api/filters distinct values). The Edit-Tags master lists
  // (D.ROSTER / D.EVENTS / …) are intentionally NOT used here.
  const L = D.LIB || { players: [], events: [], moods: [], actions: [], jerseyTypes: [], locations: [] };
  return (
    <>
      <MultiSel values={filters.players} onChange={v => setFilter('players', v)} options={L.players} allLabel="All players" />
      <Sel value={filters.event} onChange={v => setFilter('event', v)} options={L.events} allLabel="All events" />
      <Sel value={filters.mood} onChange={v => setFilter('mood', v)} options={L.moods} allLabel="All moods" />
      <Sel value={filters.action} onChange={v => setFilter('action', v)} options={L.actions} allLabel="All actions" />
      <Sel value={filters.jerseyType} onChange={v => setFilter('jerseyType', v)} options={L.jerseyTypes} allLabel="All jersey types" />
      <Sel value={filters.location} onChange={v => setFilter('location', v)} options={L.locations} allLabel="All locations" />
    </>
  );
}

const EMPTY_FILTERS = { players: [], event: '', mood: '', action: '', jerseyType: '', location: '' };

function TableScreen({ images, onOpen }) {
  const D = window.SS_DATA;
  const [q, setQ] = useState('');
  const [filters, setFilters] = useState({ ...EMPTY_FILTERS });
  const [pageSize, setPageSize] = useState(50);   // 20 | 50 | 100 items per page
  const [page, setPage] = useState(0);            // 0-based current page

  const setFilter = (k, v) => setFilters(f => ({ ...f, [k]: v }));
  const clearAll = () => { setQ(''); setFilters({ ...EMPTY_FILTERS }); };

  const results = useMemo(() => {
    const terms = q.toLowerCase().split(/\s+/).filter(Boolean);
    let r = images.filter(rec => {
      const hay = [rec.file, ...rec.players, rec.event, rec.mood, rec.action, rec.location, rec.jersey, rec.apparel, rec.caption, rec.tournament].join(' ').toLowerCase();
      if (terms.length && !terms.every(t => hay.includes(t))) return false;
      if (filters.players.length && !filters.players.some(p => rec.players.includes(p))) return false;
      if (filters.event && rec.event !== filters.event) return false;
      if (filters.mood && rec.mood !== filters.mood) return false;
      if (filters.action && rec.action !== filters.action) return false;
      if (filters.jerseyType && rec.apparel !== filters.jerseyType) return false;
      if (filters.location && rec.location !== filters.location) return false;
      return true;
    });
    return r;
  }, [images, q, filters]);

  // ---- Client-side pagination over the filtered + sorted results ----
  // Only one page of cards is rendered at a time, so the DOM never holds thousands of
  // tiles regardless of library size. Pagination always operates on `results`, so it
  // automatically respects the active search, filters and sort.
  const total = results.length;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const curPage = Math.min(page, totalPages - 1);          // clamp (e.g. after results shrink)
  const start = curPage * pageSize;
  const pageItems = results.slice(start, start + pageSize);
  // Reset to the first page whenever the result set is re-scoped by the user.
  useEffect(() => { setPage(0); }, [q, filters, pageSize]);
  const goPage = (p) => {
    setPage(Math.max(0, Math.min(p, totalPages - 1)));
    const m = document.querySelector('.main'); if (m) m.scrollTop = 0;   // jump to top of new page
  };

  // Reusable pagination bar (rendered both above and below the grid).
  const pagerBar = totalPages > 1 ? (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, margin: '14px 0', flexWrap: 'wrap' }}>
      <button className="btn ghost sm" disabled={curPage === 0} onClick={() => goPage(0)} title="First page">« First</button>
      <button className="btn ghost sm" disabled={curPage === 0} onClick={() => goPage(curPage - 1)}>‹ Prev</button>
      <span style={{ fontSize: 13, color: 'var(--text-2)', fontVariantNumeric: 'tabular-nums', padding: '0 8px' }}>
        Page {curPage + 1} of {totalPages} · {start + 1}–{Math.min(start + pageSize, total)} of {total}
      </span>
      <button className="btn ghost sm" disabled={curPage >= totalPages - 1} onClick={() => goPage(curPage + 1)}>Next ›</button>
      <button className="btn ghost sm" disabled={curPage >= totalPages - 1} onClick={() => goPage(totalPages - 1)} title="Last page">Last »</button>
    </div>
  ) : null;

  // `players` is an array (multi-select); the rest are single-value strings.
  const otherChips = Object.entries(filters).filter(([k, v]) => k !== 'players' && v);
  const hasActive = !!q || filters.players.length > 0 || otherChips.length > 0;

  return (
    <div className="screen-pad">
      <div className="section-head" style={{ marginBottom: 16 }}>
        <h1>Metadata Table</h1>
        <span className="sub">{images.length} files tagged</span>
        <span style={{ flex: 1 }} />
        <div className="seg" title="Items per page">
          {[20, 50, 100].map(n => (
            <button key={n} className={pageSize === n ? 'on' : ''} onClick={() => setPageSize(n)}>{n}</button>
          ))}
        </div>
      </div>

      {/* Search */}
      <div style={{ display: 'flex', gap: 10, marginBottom: 12 }}>
        <div className="field" style={{ flex: 1, height: 48 }}>
          <Icon name="search" size={19} />
          <input value={q} onChange={e => setQ(e.target.value)}
            placeholder='Search captions, players, scenes — try "Dhoni batting", "celebration yellow jersey", "nets"…' />
          {q && <button className="btn ghost icon sm" onClick={() => setQ('')}><Icon name="close" size={15} /></button>}
        </div>
      </div>

      {/* Filters */}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', marginBottom: 18 }}>
        <span style={{ color: 'var(--text-3)', display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12.5, fontWeight: 600, paddingRight: 2 }}>
          <Icon name="filter" size={15} /> Filter
        </span>
        <FilterDropdowns filters={filters} setFilter={setFilter} D={D} />
        {hasActive && (
          <button className="btn ghost sm" onClick={clearAll} style={{ color: 'var(--accent)' }}>Clear all</button>
        )}
      </div>

      {/* Result meta + active chips */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14, flexWrap: 'wrap' }}>
        <b style={{ fontSize: 14, fontWeight: 700, fontVariantNumeric: 'tabular-nums' }}>{results.length}</b>
        <span style={{ fontSize: 13.5, color: 'var(--text-2)', marginLeft: -4 }}>file{results.length !== 1 ? 's' : ''} found</span>
        {filters.players.map(p => (
          <Chip key={'player:' + p} kind="blue" onRemove={() => setFilter('players', filters.players.filter(x => x !== p))}>{p}</Chip>
        ))}
        {otherChips.map(([k, v]) => (
          <Chip key={k} kind="blue" onRemove={() => setFilter(k, '')}>{v}</Chip>
        ))}
      </div>

      {/* Pagination (top — below filters) */}
      {pagerBar}

      {results.length === 0 ? (
        <div className="empty">
          <div className="empty-icon"><Icon name="search" size={28} stroke={1.4} /></div>
          <h3>No matches</h3>
          <p>Nothing matches your search and filters. Try broadening your terms or clearing a filter.</p>
          <button className="btn sm" onClick={clearAll}>Clear all filters</button>
        </div>
      ) : (
        <div className="table-container">
          <table className="metadata-table">
            <thead>
              <tr>
                <th>Thumbnail</th>
                <th>File Name</th>
                <th>Folder</th>
                <th>Players</th>
                <th>Event</th>
                <th>Mood</th>
                <th>Action</th>
                <th>Location</th>
                <th>Jersey Colour</th>
                <th>Apparel</th>
                <th>Crowd Present</th>
                <th>Caption</th>
                <th>Logos / Branding</th>
                <th>Tournament</th>
                <th>Shot Type</th>
                <th>Focus</th>
                <th>Date</th>
                <th>Time of Day</th>
              </tr>
            </thead>
            <tbody>
              {pageItems.map(rec => (
                <tr key={rec.id} onClick={() => onOpen(rec, results, (i) => setPage(Math.floor(i / pageSize)))}>
                  <td className="cell-thumb">
                    <img src={`/api/thumb?id=${rec.id}`} alt="thumbnail" loading="lazy" />
                  </td>
                  <td className="cell-file" title={rec.file}>{rec.file}</td>
                  <td className="cell-folder" title={rec.folder}>{rec.folder}</td>
                  <td title={rec.players.join(', ')}>{rec.players.join(', ')}</td>
                  <td title={rec.event}>{rec.event}</td>
                  <td title={rec.mood}>{rec.mood}</td>
                  <td title={rec.action}>{rec.action}</td>
                  <td title={rec.location}>{rec.location}</td>
                  <td title={rec.jersey}>{rec.jersey}</td>
                  <td title={rec.apparel}>{rec.apparel}</td>
                  <td title={rec.crowd}>{rec.crowd}</td>
                  <td className="cell-caption" title={rec.caption}>{rec.caption}</td>
                  <td title={rec.logos_branding}>{rec.logos_branding}</td>
                  <td title={rec.tournament}>{rec.tournament}</td>
                  <td title={rec.shot_type}>{rec.shot_type}</td>
                  <td title={rec.focus}>{rec.focus}</td>
                  <td title={rec.dateOriginal}>{rec.dateOriginal}</td>
                  <td title={rec.time_of_day}>{rec.time_of_day}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      
      {/* Pagination (bottom) */}
      {pagerBar}
    </div>
  );
}

Object.assign(window, { TableScreen });

