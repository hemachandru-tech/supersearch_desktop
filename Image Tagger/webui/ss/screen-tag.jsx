/* Tag & Import screen — folder picker → live processing pipeline */

const PIPELINE_STEPS = [
  ['folder', 'Scan folder', 'Find new photos to tag'],
  ['faces', 'Find people', 'Detect & recognise players'],
  ['sparkles', 'Read the scene', 'Action, mood, event & caption'],
  ['layers', 'Confirm', 'Cross-check people with the scene'],
  ['save', 'Save tags', 'Write tags into each photo'],
  ['db', 'Add to library', 'Make it instantly searchable'],
];

function TagScreen({ images, onIndexed }) {
  const [path, setPath] = useState('');
  const [sub, setSub] = useState(true);
  const [retag, setRetag] = useState(true);
  const [disableAiTags, setDisableAiTags] = useState(false);
  const [tournamentContext, setTournamentContext] = useState("");
  const [teamContext, setTeamContext] = useState("");
  const [phase, setPhase] = useState('idle'); // idle | running | paused | done
  const [i, setI] = useState(0);
  const [total, setTotal] = useState(0);
  const [log, setLog] = useState([]);
  const [stats, setStats] = useState({ tagged: 0, skipped: 0, errors: 0, faces: 0 });
  const [t0, setT0] = useState(0);
  const [now, setNow] = useState(0);
  const [backendRate, setBackendRate] = useState(0);
  const [backendEta, setBackendEta] = useState(0);
  const [backendElapsed, setBackendElapsed] = useState(0);

  const [apiKey, setApiKey] = useState('');
  const [hasKey, setHasKey] = useState(true);
  const [model, setModel] = useState('gemini-2.5-flash');

  const tick = useRef(null);

  // On mount: resume a running job, otherwise default the folder to the LAST one used.
  useEffect(() => {
    async function init() {
      try {
        const p = await window.api.progress();
        const s = await window.api.settings();
        setTournamentContext(s.tournament || "");
        setHasKey(s.has_key);
        if (p.running) {
          setPhase('running');
          if (p.folder) setPath(p.folder);
          return;
        }
      } catch (err) {}
      try {
        const s = await fetch('/api/status').then(r => r.json());
        if (s && s.last_folder) setPath(s.last_folder);
        if (s) {
            setHasKey(s.api_keys > 0);
            if (s.gemini_model) setModel(s.gemini_model);
        }
      } catch (err) {}
    }
    init();
  }, []);

  // Poll progress from backend while running or stopping
  useEffect(() => {
    if (phase !== 'running' && phase !== 'stopping') return;
    
    const fetchProgress = async () => {
      try {
        const p = await window.api.progress();
        const s = await window.api.settings();
        setTournamentContext(s.tournament || "");
        setHasKey(s.has_key);
        
        if (phase === 'stopping') {
          if (!p.running) {
            setPhase('idle');
            setI(0);
            setTotal(0);
            setLog([]);
          }
          return;
        }

        setI(p.done || 0);
        setTotal(p.total || 0);
        setStats({
          tagged: p.ok || 0,
          skipped: p.skipped || 0,
          errors: p.errors || 0,
          faces: p.faces || 0
        });
        setBackendRate(p.rate || 0);
        setBackendEta(p.eta_seconds || 0);
        setBackendElapsed(p.elapsed || 0);

        if (p.log) {
          // Log lines from server are sorted chronologically. Show newest on top:
          setLog([...p.log].reverse());
        }

        if (p.finished || (p.done >= p.total && p.total > 0 && !p.running)) {
          setPhase('done');
          if (onIndexed) onIndexed();
        }
      } catch (err) {
        console.error("Error fetching tagging progress:", err);
      }
    };

    fetchProgress();
    const timerId = setInterval(fetchProgress, 800);
    return () => clearInterval(timerId);
  }, [phase, onIndexed]);

  async function start() {
    setLog([]);
    setPhase('running');
    setI(0);
    setTotal(0);
    setT0(Date.now());
    setNow(Date.now());
    try {
      await window.api.startTagging(path, { recursive: sub, force: retag, disable_ai_tags: disableAiTags, tournament: tournamentContext, team: teamContext });
    } catch (err) {
      alert("Failed to start tagging: " + err.message);
      setPhase('idle');
    }
  }

  function reset() {
    if (phase === 'running' || phase === 'paused') {
      setPhase('stopping');
      window.api.stopTagging().catch(console.error);
    } else {
      setPhase('idle');
      setI(0);
      setTotal(0);
      setLog([]);
    }
  }

  const pct = total > 0 ? Math.round((i / total) * 100) : 0;
  const activeStep = phase === 'running' ? (i % PIPELINE_STEPS.length) : -1;

  if (phase === 'idle' || phase === 'stopping') {
    return (
      <div className="screen-pad">
        <div className="section-head" style={{ marginBottom: 6 }}><h1>Tag &amp; Import</h1></div>
        <p style={{ color: 'var(--text-2)', fontSize: 14, margin: '0 0 26px', maxWidth: 620, lineHeight: 1.55 }}>
          Point Super Search at a folder of photos. Your images stay on your computer — Super Search reads
          each one, recognises the players, and writes searchable tags right into the photo.
        </p>

        <div className="tag-card">
          <div className="md-label" style={{ marginBottom: 8 }}>Folder to tag</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <div style={{ display: 'flex', gap: 10 }}>
              <div className="field" style={{ flex: 1 }}>
                <Icon name="folder" size={18} />
                <input value={path} onChange={e => setPath(e.target.value)} placeholder="Paste a folder path, or use Browse... to choose a folder of photos" style={{ fontFamily: 'var(--font-mono)', fontSize: 13 }} />
              </div>
              <button className="btn" onClick={async () => {
                try {
                  const res = await window.api.browse();
                  if (res.folder) setPath(res.folder);
                } catch (e) {
                  alert("Error picking folder: " + e.message);
                }
              }}><Icon name="folder" size={16} /> Browse...</button>
            </div>
            <div style={{ display: 'flex', gap: 10 }}>
              <div className="field" style={{ flex: 1 }}>
                <Icon name="sparkles" size={18} />
                <input value={tournamentContext} onChange={e => setTournamentContext(e.target.value)} placeholder="Tournament Context (e.g. IPL 2026)" style={{ fontFamily: 'var(--font-mono)', fontSize: 13 }} />
              </div>
              <div className="field" style={{ flex: 1 }}>
                <Icon name="users" size={18} />
                <input value={teamContext} onChange={e => setTeamContext(e.target.value)} placeholder="Team Context (Optional)" style={{ fontFamily: 'var(--font-mono)', fontSize: 13 }} />
              </div>
              <button className="btn primary" style={{ minWidth: 140 }} onClick={start} disabled={!path || phase === 'stopping'}>
              {phase === 'stopping' ? (
                <span><span className="spin" style={{ display: 'inline-block', width: 14, height: 14, border: '2px solid rgba(255,255,255,0.15)', borderTopColor: '#fff', borderRadius: '50%', animation: 'spin 0.8s linear infinite', marginRight: 6 }} />Stopping...</span>
              ) : (
                <span><Icon name="sparkles" size={16} /> Start Tagging</span>
              )}
            </button>
            </div>
          </div>
          <div style={{ display: 'flex', gap: 22, marginTop: 16 }}>
            <Check checked={sub} onChange={setSub} label="Include sub-folders" />
            <Check checked={retag} onChange={setRetag} label="Re-tag photos that are already tagged" />
            <Check checked={disableAiTags} onChange={setDisableAiTags} label="Disable AI Tags (Offline only)" />
          </div>
        </div>

        <div className="tag-card" style={{ marginTop: 16 }}>
          <div className="md-label" style={{ marginBottom: 8 }}>Gemini API Settings</div>
          {!hasKey && <p style={{ color: 'var(--warn)', fontSize: 13, marginBottom: 10 }}>You need a Gemini API Key to use the AI tagging features.</p>}
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            <div className="field" style={{ flex: 2, minWidth: 200 }}>
              <Icon name="key" size={18} />
              <input type="password" value={apiKey} onChange={e => setApiKey(e.target.value)} placeholder={hasKey ? "API Key is set (enter to change)" : "Paste your Gemini API key here"} style={{ fontFamily: 'var(--font-mono)', fontSize: 13 }} />
            </div>
            <div className="field" style={{ flex: 1, minWidth: 150 }}>
              <select value={model} onChange={e => setModel(e.target.value)} style={{ width: '100%', background: 'transparent', border: 'none', color: 'inherit', outline: 'none', fontSize: 13 }}>
                <option value="gemini-2.5-flash">Gemini 2.5 Flash</option>
                <option value="gemini-1.5-pro-latest">Gemini 1.5 Pro (Latest)</option>
                <option value="gemini-1.5-flash">Gemini 1.5 Flash</option>
                <option value="gemini-1.5-pro">Gemini 1.5 Pro</option>
              </select>
            </div>
            <button className="btn" onClick={async () => {
              try {
                await fetch('/api/settings', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({api_keys: apiKey, gemini_model: model}) });
                if (apiKey) setHasKey(true);
                setApiKey('');
                alert("Settings saved. You can now start tagging.");
              } catch (e) {
                alert("Failed to save settings.");
              }
            }}>Save Settings</button>
          </div>
        </div>

        <div className="pipe-strip">
          {PIPELINE_STEPS.map(([icon, title, desc], n) => (
            <React.Fragment key={n}>
              <div className="pipe-step">
                <div className="pipe-ic"><Icon name={icon} size={18} /></div>
                <div><div className="pipe-t">{title}</div><div className="pipe-d">{desc}</div></div>
              </div>
              {n < PIPELINE_STEPS.length - 1 && <div className="pipe-arrow"><Icon name="chevRight" size={16} /></div>}
            </React.Fragment>
          ))}
        </div>
      </div>
    );
  }


  const done = i;
  const elapsed = backendElapsed;
  const rate = backendRate;
  const eta = backendEta;

  return (
    <div className="screen-pad">
      <div className="section-head" style={{ marginBottom: 18 }}>
        <h1>{phase === 'done' ? 'Tagging complete' : 'Tagging in progress'}</h1>
        <code style={{ fontSize: 12.5, color: 'var(--text-3)', fontFamily: 'var(--font-mono)' }}>{path}</code>
        <span style={{ flex: 1 }} />
        {phase === 'running' && <button className="btn sm" onClick={() => setPhase('paused')}><Icon name="pause" size={14} /> Pause</button>}
        {phase === 'paused' && <button className="btn primary sm" onClick={() => setPhase('running')}><Icon name="play" size={14} /> Resume</button>}
        {phase !== 'done' && <button className="btn ghost sm" onClick={reset} style={{ color: 'var(--danger)' }}>Stop</button>}
        {phase === 'done' && <button className="btn primary sm" onClick={reset}><Icon name="check" size={15} /> Done</button>}
      </div>

      {/* progress */}
      <div className="prog-wrap">
        <div className="prog-top">
          <span><b style={{ fontVariantNumeric: 'tabular-nums' }}>{done}</b> / {total} processed</span>
          <span style={{ color: 'var(--accent)', fontWeight: 700, fontVariantNumeric: 'tabular-nums' }}>{pct}%</span>
        </div>
        <div className="prog-bar"><div style={{ width: pct + '%' }} className={phase === 'running' ? 'live' : ''} /></div>
      </div>

      {/* stat cards */}
      <div className="stat-row">
        <Stat icon="check" tone="ok" label="Photos tagged" value={stats.tagged} />
        <Stat icon="skip" tone="" label="Already tagged" value={stats.skipped} />
        <Stat icon="faces" tone="" label="People found" value={stats.faces} />
        <Stat icon="alert" tone="danger" label="Needs attention" value={stats.errors} />
        <Stat icon="bolt" tone="accent" label="Speed" value={rate ? rate.toFixed(1) : '—'} unit="/s" />
        <Stat icon="clock" tone="" label={phase === 'done' ? 'Elapsed' : 'ETA'} value={phase === 'done' ? elapsed + 's' : (eta ? eta + 's' : '—')} />
      </div>

      <div className="proc-grid">
        {/* live pipeline */}
        <div className="panel">
          <div className="panel-h"><Icon name="cpu" size={16} /> Steps</div>
          <div className="pipe-vert">
            {PIPELINE_STEPS.map(([icon, title], n) => (
              <div key={n} className={'pv-step' + (phase === 'running' && n === activeStep ? ' active' : '')}>
                <div className="pv-ic"><Icon name={icon} size={15} /></div>
                <span>{title}</span>
                {phase === 'running' && n === activeStep && <span className="pv-pulse" />}
              </div>
            ))}
          </div>
        </div>

        {/* live log */}
        <div className="panel" style={{ flex: 1 }}>
          <div className="panel-h"><Icon name="list" size={16} /> Activity log
            <span style={{ flex: 1 }} />
            {phase === 'running' && <span className="live-dot">live</span>}
          </div>
          <div className="log" style={{ overflowY: 'auto', maxHeight: '350px' }}>
            {log.length === 0 && <div className="log-empty">Waiting for first image…</div>}
            {log.map((line, n) => {
              let kind = 'ok';
              if (line.includes('ERROR') || line.includes('failed')) kind = 'error';
              else if (line.includes('skipped')) kind = 'skip';
              
              // Extract filename if format: "[1/10] filename.jpg -> Dhoni | ..." or "ERROR tagging filename.jpg: ..."
              let file = '';
              let msg = line;
              const matches = line.match(/\]\s+([^\s]+)\s+->\s+(.*)/) || line.match(/tagging\s+([^\s:]+):\s+(.*)/);
              if (matches) {
                file = matches[1];
                msg = matches[2];
              }

              return (
                <div key={n} className={'log-row ' + kind}>
                  <span className={'log-ic ' + kind}>
                    <Icon name={kind === 'ok' ? 'check' : kind === 'skip' ? 'skip' : 'alert'} size={13} stroke={2.2} />
                  </span>
                  {file ? <code className="log-file">{file}</code> : null}
                  <span className="log-msg">{msg}</span>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}

function Stat({ icon, label, value, unit, tone }) {
  const color = tone === 'ok' ? 'var(--ok)' : tone === 'danger' ? 'var(--danger)' : tone === 'accent' ? 'var(--accent)' : 'var(--text)';
  return (
    <div className="stat">
      <div className="stat-ic" style={{ color }}><Icon name={icon} size={16} /></div>
      <div className="stat-v" style={{ color }}>{value}{unit && <em>{unit}</em>}</div>
      <div className="stat-l">{label}</div>
    </div>
  );
}

Object.assign(window, { TagScreen });








