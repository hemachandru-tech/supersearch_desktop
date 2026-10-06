/* Player Management Screen */

const { useState, useEffect } = React;

function PlayersScreen() {
  const [players, setPlayers] = useState([]);
  const [models, setModels] = useState([]);
  const [activeModel, setActiveModel] = useState(null);
  
  const [selectedPlayer, setSelectedPlayer] = useState(null);
  const [showAddPlayer, setShowAddPlayer] = useState(false);
  const [newPlayerName, setNewPlayerName] = useState("");
  const [newPlayerAliases, setNewPlayerAliases] = useState("");
  
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [showModels, setShowModels] = useState(false);
  
  const [searchTerm, setSearchTerm] = useState("");

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    setLoading(true);
    setError(null);
    try {
      const pRes = await fetch('/api/players').then(r => r.json());
      const mRes = await fetch('/api/models').then(r => r.json());
      const aRes = await fetch('/api/models/active').then(r => r.json());
      setPlayers(pRes || []);
      setModels(mRes || []);
      setActiveModel(aRes);
    } catch (e) {
      console.error(e);
      setError("Unable to load player management data.");
    }
    setLoading(false);
  };

  const handleAddPlayer = async () => {
    if (!newPlayerName.trim()) return;
    try {
      await fetch('/api/players', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: newPlayerName, aliases: newPlayerAliases })
      });
      setShowAddPlayer(false);
      setNewPlayerName("");
      setNewPlayerAliases("");
      loadData();
    } catch (e) {
      alert("Error adding player");
    }
  };

  if (showModels) return <ModelsScreen models={models} onBack={() => setShowModels(false)} onRefresh={loadData} />;
  if (selectedPlayer) {
    return <PlayerDetailScreen player={selectedPlayer} onBack={() => { setSelectedPlayer(null); loadData(); }} />;
  }

  const filteredPlayers = players.filter(p => {
    if (!searchTerm) return true;
    const term = searchTerm.toLowerCase();
    const nameMatch = p.name && p.name.toLowerCase().includes(term);
    const aliasMatch = p.aliases && p.aliases.toLowerCase().includes(term);
    return nameMatch || aliasMatch;
  });

  return (
    <div className="scroll-y" style={{ padding: '40px', backgroundColor: 'var(--bg-body)', color: 'var(--text)' }}>
      <div style={{ maxWidth: 1400, width: 'calc(100% - 64px)', margin: '0 auto' }}>
        
        {/* Header */}
        <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 30 }}>
          <div>
            <h2 style={{ margin: '0 0 8px', fontSize: 28, fontWeight: 600, color: 'var(--text)' }}>Player Management</h2>
            <p style={{ margin: 0, color: 'var(--text-dim)', fontSize: 16 }}>Manage players and prepare the player recognition model for your league.</p>
          </div>
          <button className="btn primary" onClick={() => setShowAddPlayer(true)} style={{ padding: '10px 20px', fontSize: 15, fontWeight: 500 }}>+ Add Player</button>
        </header>

        {showAddPlayer && (
          <div style={{ background: 'var(--bg-card)', padding: 24, borderRadius: 12, marginBottom: 30, border: '1px solid var(--border)', boxShadow: '0 2px 8px rgba(0,0,0,0.04)' }}>
            <h3 style={{ margin: '0 0 16px', fontSize: 18, fontWeight: 600 }}>Add New Player</h3>
            <div className="row" style={{ gap: 12 }}>
              <input type="text" className="input" placeholder="Player Name" value={newPlayerName} onChange={e => setNewPlayerName(e.target.value)} style={{ flex: 1, padding: '10px 14px', fontSize: 15 }} />
              <input type="text" className="input" placeholder="Aliases (optional, comma separated)" value={newPlayerAliases} onChange={e => setNewPlayerAliases(e.target.value)} style={{ flex: 1, padding: '10px 14px', fontSize: 15 }} />
              <button className="btn primary" onClick={handleAddPlayer} style={{ padding: '10px 24px', fontSize: 15 }}>Save</button>
              <button className="btn" onClick={() => setShowAddPlayer(false)} style={{ padding: '10px 24px', fontSize: 15 }}>Cancel</button>
            </div>
            <p style={{ margin: '12px 0 0', fontSize: 13, color: 'var(--text-dim)' }}>Aliases are alternate names used to search for or refer to this player. They do not create separate recognition classes.</p>
          </div>
        )}

        {/* Current Model Card */}
        <section style={{ marginBottom: 40 }}>
          {loading ? (
            <div style={{ background: 'var(--bg-card)', padding: 32, borderRadius: 12, border: '1px solid var(--border)', boxShadow: '0 2px 12px rgba(0,0,0,0.03)' }}>Loading model...</div>
          ) : error ? (
            <div style={{ background: 'var(--bg-card)', padding: 32, borderRadius: 12, border: '1px solid var(--border)', color: '#d32f2f', boxShadow: '0 2px 12px rgba(0,0,0,0.03)' }}>
              {error}
              <br/><button className="btn" style={{marginTop: 12}} onClick={loadData}>Retry</button>
            </div>
          ) : activeModel ? (
            <div style={{ background: 'var(--bg-card)', padding: '32px 40px', borderRadius: 12, border: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center', boxShadow: '0 4px 16px rgba(0,0,0,0.04)' }}>
              <div>
                <div style={{ display: 'flex', alignItems: 'center', marginBottom: 12 }}>
                  <div style={{ width: 12, height: 12, borderRadius: '50%', background: 'var(--accent)', marginRight: 10, boxShadow: '0 0 8px var(--accent)' }}></div>
                  <span style={{ fontWeight: 700, fontSize: 13, letterSpacing: 1.2, color: 'var(--text)', textTransform: 'uppercase' }}>ACTIVE</span>
                </div>
                <h3 style={{ margin: '0 0 16px', fontSize: 24, fontWeight: 600 }}>{activeModel.version_name}</h3>
                <div style={{ display: 'flex', gap: 32, color: 'var(--text-dim)', fontSize: 15 }}>
                  <div><b style={{color: 'var(--text)'}}>{activeModel.players_count}</b> Players</div>
                  <div><b style={{color: 'var(--text)'}}>{activeModel.samples_count}</b> {activeModel.status === 'LEGACY' ? 'Reference Samples' : 'Training Samples'}</div>
                  <div>Updated {new Date(activeModel.created_at).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })}</div>
                </div>
              </div>
              <button className="btn" onClick={() => setShowModels(true)} style={{ padding: '10px 24px', fontSize: 15, fontWeight: 500, backgroundColor: 'var(--bg-body)' }}>Manage Models</button>
            </div>
          ) : (
            <div style={{ background: 'var(--bg-card)', padding: 32, borderRadius: 12, border: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center', boxShadow: '0 2px 12px rgba(0,0,0,0.03)' }}>
              <div>
                <h3 style={{ margin: '0 0 8px', fontSize: 18, fontWeight: 600 }}>No active player recognition model</h3>
                <p style={{ margin: 0, color: 'var(--text-dim)' }}>Train a model to enable automatic face tagging.</p>
              </div>
              <button className="btn" onClick={() => setShowModels(true)} style={{ padding: '10px 24px', fontSize: 15, fontWeight: 500 }}>Train Model</button>
            </div>
          )}
        </section>

        {/* Players Grid */}
        <section>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
            <h3 style={{ margin: 0, fontSize: 16, letterSpacing: 1, textTransform: 'uppercase', color: 'var(--text-dim)', fontWeight: 600 }}>
              PLAYERS <span style={{ marginLeft: 16, fontSize: 14, fontWeight: 400, color: 'var(--text-dim)' }}>{players.length} players</span>
            </h3>
            
            <div style={{ display: 'flex', gap: 12 }}>
              <div style={{ position: 'relative' }}>
                <span style={{ position: 'absolute', left: 14, top: 10, color: '#999', fontSize: 14 }}>🔍</span>
                <input 
                  type="text" 
                  className="input" 
                  placeholder="Search players..." 
                  value={searchTerm} 
                  onChange={e => setSearchTerm(e.target.value)} 
                  style={{ padding: '10px 14px 10px 36px', fontSize: 14, width: 260, borderRadius: 8, border: '1px solid var(--border)' }} 
                />
              </div>
            </div>
          </div>
          
          {loading ? (
             <div style={{ background: 'var(--bg-card)', padding: 40, borderRadius: 12, border: '1px solid var(--border)', textAlign: 'center', color: 'var(--text-dim)' }}>Loading players...</div>
          ) : error ? null : players.length === 0 ? (
             <div style={{ background: 'var(--bg-card)', padding: 60, borderRadius: 12, border: '1px dashed var(--border)', textAlign: 'center', color: 'var(--text-dim)' }}>
                <p style={{ fontSize: 18, fontWeight: 500, color: 'var(--text)', marginBottom: 12 }}>No players added yet</p>
                <p style={{ marginBottom: 24, maxWidth: 400, margin: '0 auto 24px' }}>Add players and training samples to prepare the recognition model for your league.</p>
                <button className="btn primary" onClick={() => setShowAddPlayer(true)} style={{ padding: '10px 24px', fontSize: 15 }}>+ Add Player</button>
             </div>
          ) : filteredPlayers.length === 0 ? (
             <div style={{ background: 'var(--bg-card)', padding: 60, borderRadius: 12, border: '1px solid var(--border)', textAlign: 'center', color: 'var(--text-dim)' }}>
                <p style={{ fontSize: 18, fontWeight: 500, color: 'var(--text)', marginBottom: 12 }}>No players found</p>
                <p style={{ margin: 0 }}>Try a different search term.</p>
             </div>
          ) : (
             <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))', gap: 20 }}>
                {filteredPlayers.map(p => (
                   <div key={p.id} style={{ background: 'var(--bg-card)', padding: 20, borderRadius: 12, border: '1px solid var(--border)', display: 'flex', alignItems: 'center', transition: 'box-shadow 0.2s ease, transform 0.2s ease', cursor: 'default' }}
                        onMouseEnter={e => { e.currentTarget.style.boxShadow = '0 4px 12px rgba(0,0,0,0.06)'; e.currentTarget.style.transform = 'translateY(-2px)'; }}
                        onMouseLeave={e => { e.currentTarget.style.boxShadow = 'none'; e.currentTarget.style.transform = 'translateY(0)'; }}
                   >
                      <div style={{ width: 56, height: 56, borderRadius: '50%', background: 'linear-gradient(135deg, #f0f0f0, #e0e0e0)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#555', fontWeight: 600, fontSize: 22, marginRight: 16, flexShrink: 0 }}>
                         {p.name.charAt(0)}
                      </div>
                      
                      <div style={{ flex: 1, minWidth: 0 }}>
                         <div style={{ fontWeight: 600, fontSize: 16, color: 'var(--text)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', marginBottom: 2 }}>{p.name}</div>
                         {p.aliases && <div style={{ fontSize: 13, color: 'var(--text-3)', marginBottom: 4, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{p.aliases}</div>}
                         <div style={{ fontSize: 13, color: 'var(--text-dim)' }}>{p.sample_count} training samples</div>
                      </div>
                      
                      <button className="btn" style={{ padding: '8px 16px', fontSize: 14, marginLeft: 12, backgroundColor: 'transparent', border: '1px solid var(--border)' }} onClick={() => setSelectedPlayer(p)}>View</button>
                   </div>
                ))}
             </div>
          )}
        </section>
      </div>
    </div>
  );
}

function PlayerDetailScreen({ player, onBack }) {
  const [samples, setSamples] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showAddSamples, setShowAddSamples] = useState(false);
  const [extracting, setExtracting] = useState(false);
  const [extractionResults, setExtractionResults] = useState(null);
  const [seasonContext, setSeasonContext] = useState("");
  const [leagueContext, setLeagueContext] = useState("");
  const [teamContext, setTeamContext] = useState("");
  const [sourceTypeContext, setSourceTypeContext] = useState("");
  const [selectedFaces, setSelectedFaces] = useState({});

  useEffect(() => {
    loadSamples();
  }, [player.id]);

  const loadSamples = async () => {
    setLoading(true);
    try {
      const data = await fetch('/api/samples/' + player.id).then(r => r.json());
      setSamples(data || []);
    } catch (e) {
      console.error(e);
    }
    setLoading(false);
  };

  const removeSample = async (id) => {
    if (!confirm("Remove this training sample?")) return;
    await fetch('/api/samples/' + id, { method: 'DELETE' });
    setSamples(samples.filter(s => s.id !== id));
  };

  const handleBrowseSamples = async () => {
    try {
      const res = await fetch("/api/pick-folder", { method: "POST" }).then((r) => r.json());
      if (res.folder) {
        setExtracting(true);
        const fRes = await fetch("/api/list-files", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ folder: res.folder })
        }).then(r => r.json());
        
        if (fRes.files && fRes.files.length > 0) {
          const exRes = await fetch("/api/samples/extract", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ files: fRes.files })
          }).then(r => r.json());
          
          const sels = {};
          (exRes.results || []).forEach(r => {
             if (r.status === 'SINGLE_FACE') sels[r.file] = 0;
          });
          setSelectedFaces(sels);
          setExtractionResults(exRes.results || []);
        } else {
          alert("No valid images found in folder.");
        }
        setExtracting(false);
      }
    } catch (e) {
      alert("Error processing folder");
      setExtracting(false);
    }
  };

  const handleConfirmSamples = async () => {
    if (!extractionResults) return;
    const toConfirm = [];
    extractionResults.forEach(r => {
      if (r.status === 'SINGLE_FACE' || r.status === 'MULTIPLE_FACES') {
        const idx = selectedFaces[r.file];
        if (idx !== undefined && r.faces[idx]) {
          toConfirm.push({
            file: r.file,
            bbox: r.faces[idx].bbox,
            embedding: r.faces[idx].embedding
          });
        }
      }
    });

    if (toConfirm.length === 0) {
      alert("No valid faces selected.");
      return;
    }

    try {
      const res = await fetch("/api/samples/confirm", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          player_id: player.id,
          league: leagueContext,
          season: seasonContext,
          team: teamContext,
          source_type: sourceTypeContext,
          samples: toConfirm
        })
      }).then(r => r.json());

      alert(`Added: ${res.inserted}. Skipped duplicates: ${res.skipped}.`);
      setShowAddSamples(false);
      setExtractionResults(null);
      loadSamples();
    } catch (e) {
      alert("Error confirming samples");
    }
  };

  if (showAddSamples) {
    // Calculate summary stats
    const totalImages = extractionResults ? extractionResults.length : 0;
    let totalFaces = 0;
    let totalSelected = 0;
    
    if (extractionResults) {
        extractionResults.forEach(r => {
            if (r.faces) totalFaces += r.faces.length;
            if (selectedFaces[r.file] !== undefined) totalSelected += 1;
        });
    }

    return (
      <div className="scroll-y" style={{ padding: 40, backgroundColor: 'var(--bg-body)', color: 'var(--text)' }}>
        <div style={{ maxWidth: 1400, margin: '0 auto', width: 'calc(100% - 64px)' }}>
          
          <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 24 }}>
            <div>
              <h2 style={{ margin: '0 0 8px', fontSize: 24, fontWeight: 600 }}>Review Training Samples</h2>
              <div style={{ fontSize: 16, color: 'var(--text-dim)', marginBottom: 12 }}>
                Adding samples for: <strong style={{ color: 'var(--text)' }}>{player.name}</strong>
              </div>
              <p style={{ margin: 0, color: 'var(--text-dim)', fontSize: 15 }}>
                Review the detected faces and select the ones that belong to this player. Confirmed faces will be added to the player's training samples.
              </p>
            </div>
          </header>

          <div style={{ background: 'var(--bg-card)', padding: 24, borderRadius: 12, border: '1px solid var(--border)', marginBottom: 30, boxShadow: '0 2px 12px rgba(0,0,0,0.03)' }}>
            <div className="row" style={{ gap: 16, marginBottom: 20 }}>
              <input type="text" className="input" placeholder="League (e.g. IPL)" value={leagueContext} onChange={e => setLeagueContext(e.target.value)} style={{ padding: '10px 14px', fontSize: 15, flex: 1 }} />
              <input type="text" className="input" placeholder="Season (e.g. 2026)" value={seasonContext} onChange={e => setSeasonContext(e.target.value)} style={{ padding: '10px 14px', fontSize: 15, flex: 1 }} />
              <input type="text" className="input" placeholder="Team (e.g. CSK)" value={teamContext} onChange={e => setTeamContext(e.target.value)} style={{ padding: '10px 14px', fontSize: 15, flex: 1 }} />
              <input type="text" className="input" placeholder="Source Type (e.g. Match Photo)" value={sourceTypeContext} onChange={e => setSourceTypeContext(e.target.value)} style={{ padding: '10px 14px', fontSize: 15, flex: 1 }} />
            </div>
            {!extractionResults && !extracting && (
               <button className="btn primary" onClick={handleBrowseSamples} style={{ padding: '10px 24px', fontSize: 15 }}>Browse Folder for Images</button>
            )}
            {extracting && <p style={{ color: 'var(--text-dim)', margin: 0 }}>Extracting faces via InsightFace... Please wait.</p>}
          </div>

          {extractionResults && (
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24, paddingBottom: 16, borderBottom: '1px solid var(--border)' }}>
                <div style={{ fontSize: 15, fontWeight: 500, color: 'var(--text)' }}>
                  {totalImages} images · {totalFaces} faces detected · {totalSelected} selected
                </div>
                <div style={{ display: 'flex', gap: 12 }}>
                  <button className="btn" onClick={() => setShowAddSamples(false)} style={{ padding: '10px 24px', fontSize: 15 }}>Cancel</button>
                  <button 
                    className="btn primary" 
                    onClick={handleConfirmSamples} 
                    disabled={totalSelected === 0}
                    style={{ padding: '10px 24px', fontSize: 15, opacity: totalSelected === 0 ? 0.5 : 1 }}
                  >
                    {totalSelected === 0 ? "Select Faces" : `Add ${totalSelected} Face${totalSelected > 1 ? 's' : ''} to ${player.name}`}
                  </button>
                </div>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: 24 }}>
                {extractionResults.map(r => {
                  const filename = r.file.split(/[\/]/).pop();
                  
                  if (r.status === 'ERROR' || r.status === 'NO_FACE') {
                      return (
                        <div key={r.file} style={{ background: 'var(--bg-card)', borderRadius: 12, border: '1px solid var(--border)', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
                          <div style={{ height: 260, background: '#f5f5f5', display: 'flex', alignItems: 'center', justifyContent: 'center', flexDirection: 'column', padding: 20, textAlign: 'center', color: 'var(--text-dim)' }}>
                             <div style={{ fontSize: 32, marginBottom: 12 }}>∅</div>
                             <div style={{ fontWeight: 500, color: 'var(--text)', marginBottom: 8 }}>No face detected</div>
                             <div style={{ fontSize: 13 }}>This image cannot be added as a training sample.</div>
                          </div>
                          <div style={{ padding: 16, borderTop: '1px solid var(--border)', background: '#fafafa' }}>
                             <div style={{ fontWeight: 500, fontSize: 14, color: 'var(--text)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={filename}>{filename}</div>
                             <div style={{ fontSize: 12, color: '#d32f2f', marginTop: 4 }}>{r.status.replace('_', ' ')}</div>
                          </div>
                        </div>
                      );
                  }

                  return (r.faces || []).map((f, i) => {
                    const isSelected = selectedFaces[r.file] === i;
                    const cropUrl = "/api/face_crop?file=" + encodeURIComponent(r.file) + "&bbox=" + encodeURIComponent(JSON.stringify(f.bbox));
                    
                    return (
                      <div 
                        key={`${r.file}-${i}`} 
                        onClick={() => {
                            if (isSelected) {
                                const newSels = { ...selectedFaces };
                                delete newSels[r.file];
                                setSelectedFaces(newSels);
                            } else {
                                setSelectedFaces({ ...selectedFaces, [r.file]: i });
                            }
                        }}
                        style={{ 
                          background: 'var(--bg-card)', 
                          borderRadius: 12, 
                          border: isSelected ? '2px solid var(--accent)' : '1px solid var(--border)',
                          boxShadow: isSelected ? '0 4px 16px rgba(255,199,44,0.15)' : 'none',
                          display: 'flex', 
                          flexDirection: 'column', 
                          overflow: 'hidden',
                          cursor: 'pointer',
                          position: 'relative',
                          transition: 'all 0.2s ease'
                        }}>
                        
                        <div style={{ height: 260, background: '#f0f0f0', position: 'relative', display: 'flex', alignItems: 'center', justifyContent: 'center', overflow: 'hidden' }}>
                           <img 
                              src={cropUrl} 
                              alt="Face Crop" 
                              style={{ width: '100%', height: '100%', objectFit: 'contain' }}
                              onError={(e) => {
                                  e.target.onerror = null;
                                  e.target.style.display = 'none';
                                  e.target.nextSibling.style.display = 'block';
                              }}
                           />
                           <div style={{ display: 'none', color: 'var(--text-dim)', fontSize: 13, textAlign: 'center', padding: 20 }}>
                              Could not load crop.<br/>BBox: [{Math.round(f.bbox[0])}, {Math.round(f.bbox[1])}, {Math.round(f.bbox[2])}, {Math.round(f.bbox[3])}]
                           </div>
                           
                           {isSelected && (
                             <div style={{ position: 'absolute', bottom: 12, right: 12, width: 28, height: 28, background: 'var(--accent)', borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#000', fontWeight: 'bold', fontSize: 16, boxShadow: '0 2px 8px rgba(0,0,0,0.2)' }}>
                               ✓
                             </div>
                           )}
                           {!isSelected && (
                             <div style={{ position: 'absolute', bottom: 12, right: 12, width: 28, height: 28, background: 'rgba(255,255,255,0.8)', border: '1px solid var(--border)', borderRadius: '50%' }}>
                             </div>
                           )}
                        </div>
                        
                        <div style={{ padding: 16, borderTop: '1px solid var(--border)', background: isSelected ? 'rgba(255,199,44,0.05)' : '#fafafa' }}>
                           <div style={{ fontWeight: 500, fontSize: 14, color: 'var(--text)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={filename}>{filename}</div>
                           <div style={{ fontSize: 13, color: 'var(--text-dim)', marginTop: 4 }}>
                              {r.faces.length === 1 ? 'Single face detected' : `Face ${i+1} of ${r.faces.length} detected`}
                           </div>
                        </div>
                      </div>
                    );
                  });
                })}
              </div>
            </div>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="scroll-y" style={{ padding: 40, backgroundColor: 'var(--bg-body)', color: 'var(--text)' }}>
      <div style={{ maxWidth: 1000, margin: '0 auto' }}>
        <button className="btn" onClick={onBack} style={{ marginBottom: 20 }}>← Back to Players</button>
        <header style={{ marginBottom: 40, display: 'flex', alignItems: 'center', gap: 20 }}>
          <div style={{ width: 80, height: 80, borderRadius: '50%', background: '#e0e0e0', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#757575', fontWeight: 'bold', fontSize: 32 }}>
            {player.name.charAt(0)}
          </div>
          <div>
             <h2 style={{ margin: '0 0 8px', fontSize: 32, fontWeight: 600 }}>{player.name}</h2>
             <p style={{ margin: 0, fontSize: 16, color: 'var(--text-dim)' }}>{player.aliases ? `Aliases: ${player.aliases}` : "No aliases"}</p>
          </div>
        </header>

        <section>
          <div className="row" style={{ justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
            <h3 style={{ margin: 0, fontSize: 18 }}>Training Samples ({samples.length})</h3>
            <button className="btn primary" onClick={() => setShowAddSamples(true)}>+ Add Samples</button>
          </div>
          
          {loading ? (
             <div style={{ background: 'var(--bg-card)', padding: 20, borderRadius: 8, border: '1px solid var(--border)' }}>Loading samples...</div>
          ) : samples.length === 0 ? (
             <div style={{ background: 'var(--bg-card)', padding: 40, borderRadius: 8, border: '1px solid var(--border)', textAlign: 'center', color: 'var(--text-dim)' }}>
                <p style={{ fontSize: 16, marginBottom: 8 }}>No training samples yet.</p>
                <button className="btn primary" onClick={() => setShowAddSamples(true)} style={{ marginTop: 12 }}>+ Add Samples</button>
             </div>
          ) : (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 16 }}>
              {samples.map(s => (
                <div key={s.id} style={{ position: 'relative', background: 'var(--bg-card)', borderRadius: 8, border: '1px solid var(--border)', padding: 16 }}>
                   <div style={{ fontSize: 10, color: 'var(--text-dim)', marginBottom: 4, fontWeight: 500, textTransform: 'uppercase' }}>{s.league} {s.season}</div>
                   <div style={{ fontSize: 11, color: 'var(--text-dim)', marginBottom: 8, fontWeight: 500 }}>{s.team}</div>
                   <div style={{ fontSize: 13, wordBreak: 'break-all', marginBottom: 8, lineHeight: 1.4 }}>{s.source_file.split(/[\\/]/).pop()}</div>
                   <div style={{ fontSize: 11, color: 'var(--text-dim)' }}>Type: {s.source_type}</div>
                   <button onClick={() => removeSample(s.id)} style={{ position: 'absolute', top: 8, right: 8, background: '#ffebee', color: '#d32f2f', border: 'none', borderRadius: 4, cursor: 'pointer', width: 24, height: 24, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>✕</button>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

function ModelsScreen({ models, onBack, onRefresh }) {
  const [training, setTraining] = useState(false);

  const handleTrain = async () => {
    if (!confirm("Train a new model using all approved training samples?")) return;
    setTraining(true);
    try {
      const res = await fetch("/api/models/train", { method: "POST" }).then(r => r.json());
      if (res.error) alert("Training failed: " + res.error);
      else alert("Model trained successfully! Version: " + res.version_name);
      onRefresh();
    } catch (e) {
      alert("Error triggering training");
    }
    setTraining(false);
  };

  const handleActivate = async (id, version) => {
    if (!confirm(`Activate ${version}?

This will make it the player recognition model used for future tagging.
The current model will remain available for rollback.`)) return;
    try {
      const res = await fetch("/api/models/activate/" + id, { method: "POST" }).then(r => r.json());
      if (res.error) alert("Activation failed: " + res.error);
      else {
        alert("Model activated successfully!");
        onRefresh();
      }
    } catch (e) {
      alert("Error activating model");
    }
  };

  return (
    <div className="scroll-y" style={{ padding: 40, backgroundColor: 'var(--bg-body)', color: 'var(--text)' }}>
      <div style={{ maxWidth: 800, margin: '0 auto' }}>
        <button className="btn" onClick={onBack} style={{ marginBottom: 20 }}>← Back to Players</button>
        <header style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 40, alignItems: 'center' }}>
          <div>
            <h2 style={{ margin: '0 0 8px', fontSize: 24, fontWeight: 600 }}>Model Versions</h2>
          </div>
          <button className="btn primary" onClick={handleTrain} disabled={training}>
            {training ? "Training..." : "Train New Model"}
          </button>
        </header>

        {models.length === 0 ? (
          <div style={{ background: 'var(--bg-card)', padding: 40, borderRadius: 8, border: '1px solid var(--border)', textAlign: 'center', color: 'var(--text-dim)' }}>
             No custom models trained yet.
          </div>
        ) : (
          models.map(m => (
            <div key={m.id} style={{ background: 'var(--bg-card)', padding: 24, borderRadius: 8, marginBottom: 16, border: '1px solid var(--border)', borderLeft: m.status === 'ACTIVE' ? '4px solid var(--accent)' : '1px solid var(--border)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                <div>
                  <h3 style={{ margin: '0 0 8px', fontSize: 18, fontWeight: 600 }}>
                    {m.version_name} 
                    {m.status === 'ACTIVE' && <span style={{ marginLeft: 12, fontSize: 12, color: 'var(--accent)', background: 'rgba(255,199,44,0.1)', padding: '4px 8px', borderRadius: 4, fontWeight: 'bold' }}>ACTIVE</span>}
                    {m.status === 'CANDIDATE' && <span style={{ marginLeft: 12, fontSize: 12, color: '#4F8DF7', background: 'rgba(79,141,247,0.1)', padding: '4px 8px', borderRadius: 4, fontWeight: 'bold' }}>CANDIDATE</span>}
                  </h3>
                  <p style={{ margin: '0 0 12px', fontSize: 14, color: 'var(--text-dim)' }}>Players: <b>{m.players_count}</b> | Samples: <b>{m.samples_count}</b></p>
                  <p style={{ margin: 0, fontSize: 12, color: 'var(--text-dim)' }}>Created: {new Date(m.created_at).toLocaleString()}</p>
                  
                  {m.metrics && (
                    <div style={{ marginTop: 16, fontSize: 13, background: 'var(--bg-body)', padding: 12, borderRadius: 6, fontFamily: 'monospace', border: '1px solid var(--border)' }}>
                      {JSON.parse(m.metrics).accuracy !== undefined ? `Evaluation Accuracy: ${(JSON.parse(m.metrics).accuracy * 100).toFixed(1)}%` : (JSON.parse(m.metrics).note || 'No evaluation metrics')}
                    </div>
                  )}
                </div>
                
                {m.status !== 'ACTIVE' && (
                  <button className="btn" onClick={() => handleActivate(m.id, m.version_name)}>
                    {m.status === 'PREVIOUS' ? 'Reactivate Model' : 'Activate Model'}
                  </button>
                )}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
