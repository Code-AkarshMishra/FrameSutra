import { useEffect, useMemo, useRef, useState } from 'react'
import { ArrowDownToLine, ArrowLeft, ArrowRight, AudioLines, Bookmark, BookOpen, BrainCircuit, Check, ChevronRight, CircleHelp, Clock3, FileAudio2, Film, FileText, Gamepad2, Globe2, Layers, Link2, LoaderCircle, Menu, MessageSquareText, Moon, Play, Plus, RefreshCw, Search, Send, Settings2, Sparkles, Star, Sun, Trash2, Upload, Video, WandSparkles, X } from 'lucide-react'

const stages = [
  ['audio', 'Prepare audio'], ['transcript', 'Transcribe speech'], ['title', 'Understand video'],
  ['summary', 'Summarize key points'], ['extract', 'Extract insights'], ['visual', 'Analyze visuals'], ['rag', 'Prepare AI chat'],
]
const API = ''
const ACTIVE_JOB_KEY = 'framesutra.activeJob'
const BATCH_JOBS_KEY = 'framesutra.batchJobs'

function App() {
  const [theme, setTheme] = useState(() => {
    const saved = localStorage.getItem('framesutra.theme')
    return saved === 'dark' || saved === 'light' ? saved : (window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
  })
  const [mode, setMode] = useState('youtube')
  const [page, setPage] = useState('workspace')
  const [language, setLanguage] = useState('english')
  const [url, setUrl] = useState('')
  const [file, setFile] = useState(null)
  const [batchFiles, setBatchFiles] = useState([])
  const [batchUrls, setBatchUrls] = useState('')
  const [visuals, setVisuals] = useState(false)
  const [jobId, setJobId] = useState('')
  const [job, setJob] = useState(null)
  const [batchJobs, setBatchJobs] = useState([])
  const [error, setError] = useState('')
  const [tab, setTab] = useState('Overview')
  const [question, setQuestion] = useState('')
  const [chat, setChat] = useState([])
  const [sending, setSending] = useState(false)
  const [libraryItems, setLibraryItems] = useState([])
  const [libraryQuery, setLibraryQuery] = useState('')
  const [libraryLoading, setLibraryLoading] = useState(false)
  const [systemMetrics, setSystemMetrics] = useState(null)
  const [systemError, setSystemError] = useState('')
  const [legalPage, setLegalPage] = useState('')
  const [agreementAccepted, setAgreementAccepted] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const inputRef = useRef(null)
  const isNotFound = !['/', '/index.html'].includes(window.location.pathname)

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    localStorage.setItem('framesutra.theme', theme)
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', theme === 'dark' ? '#101522' : '#f5f7fb')
  }, [theme])

  useEffect(() => {
    if (!jobId || ['complete', 'error', 'interrupted', 'cancelled'].includes(job?.state)) return
    let live = true
    const poll = async () => {
      try {
        const response = await fetch(`${API}/api/jobs/${jobId}`)
        const data = await response.json()
        if (live && response.ok) { setJob(data); if (data.state === 'complete') setTab('Overview'); if (data.error) setError(data.error) }
      } catch { if (live) setError('Could not connect to the FrameSutra API. Check that the backend is running.') }
    }
    poll()
    const timer = setInterval(poll, 4000)
    return () => { live = false; clearInterval(timer) }
  }, [jobId, job?.state])

  useEffect(() => {
    const legacyKeys = [['videolens.activeJob', ACTIVE_JOB_KEY], ['videolens.batchJobs', BATCH_JOBS_KEY]]
    for (const [legacyKey, currentKey] of legacyKeys) {
      const existing = localStorage.getItem(currentKey)
      const legacy = localStorage.getItem(legacyKey)
      if (!existing && legacy) localStorage.setItem(currentKey, legacy)
      if (legacy) localStorage.removeItem(legacyKey)
    }
  }, [])

  useEffect(() => {
    const savedId = localStorage.getItem(ACTIVE_JOB_KEY)
    if (!savedId) return
    fetch(`${API}/api/jobs/${savedId}`).then(r => r.ok ? r.json() : null).then(data => {
      if (data) { setJobId(savedId); setJob(data) }
      else localStorage.removeItem(ACTIVE_JOB_KEY)
    }).catch(() => {})
  }, [])

  useEffect(() => {
    const saved = localStorage.getItem(BATCH_JOBS_KEY)
    if (saved) { try { setBatchJobs(JSON.parse(saved)) } catch { localStorage.removeItem(BATCH_JOBS_KEY) } }
  }, [])

  useEffect(() => {
    if (!batchJobs.length) return
    let live = true
    const pollBatch = async () => {
      const items = await Promise.all(batchJobs.map(async item => {
        try { const response = await fetch(`${API}/api/jobs/${item.id}`); return response.ok ? await response.json() : item }
        catch { return item }
      }))
      if (live) setBatchJobs(items)
    }
    pollBatch()
    const timer = setInterval(pollBatch, 4000)
    return () => { live = false; clearInterval(timer) }
  }, [batchJobs.map(item => item.id).join(',')])

  useEffect(() => {
    if (page !== 'library') return
    let live = true; setLibraryLoading(true)
    fetch(`${API}/api/library?q=${encodeURIComponent(libraryQuery)}`).then(r => r.ok ? r.json() : []).then(data => { if (live) setLibraryItems(data) }).catch(() => { if (live) setLibraryItems([]) }).finally(() => { if (live) setLibraryLoading(false) })
    return () => { live = false }
  }, [page, libraryQuery, job?.state])

  useEffect(() => {
    if (page !== 'system') return
    const load = () => fetch(`${API}/api/metrics`).then(r => r.ok ? r.json() : Promise.reject(new Error('Metrics endpoint unavailable'))).then(setSystemMetrics).catch(err => setSystemError(err.message))
    load(); const timer = setInterval(load, 15000); return () => clearInterval(timer)
  }, [page])

  useEffect(() => {
    document.title = isNotFound ? '404 · Page not found | FrameSutra' : 'FrameSutra — Every Frame Has a Story'
  }, [isNotFound])

  const busy = job?.state === 'queued' || job?.state === 'running'
  const results = job?.result
  const transcriptWords = useMemo(() => results?.transcript?.trim().split(/\s+/).filter(Boolean).length || 0, [results])

  async function startAnalysis(event) {
    event.preventDefault(); setError(''); setJob(null); setChat([])
    if (mode === 'batch') {
      const urls = batchUrls.split(/\r?\n/).map(x => x.trim()).filter(Boolean)
      if (urls.length + batchFiles.length < 1 || urls.length + batchFiles.length > 3) { setError('A batch needs one to three total videos or files.'); return }
      const form = new FormData(); form.append('language', language); form.append('sources', JSON.stringify(urls)); form.append('include_visuals', visuals ? 'true' : 'false'); batchFiles.forEach(item => form.append('media', item))
      try {
        const response = await fetch(`${API}/api/jobs/batch`, { method: 'POST', body: form }); const data = await response.json()
        if (!response.ok) throw new Error(data.detail || 'Could not submit this batch.')
        const firstId = data.job_ids[0]; const submitted = data.job_ids.map(id => ({ id, state: 'queued', steps: {} })); setBatchJobs(submitted); localStorage.setItem(BATCH_JOBS_KEY, JSON.stringify(submitted)); setJobId(firstId); localStorage.setItem(ACTIVE_JOB_KEY, firstId); setJob({ state: 'queued', steps: {} }); setBatchUrls(''); setBatchFiles([])
      } catch (err) { setError(err.message || 'Could not submit this batch.') }
      return
    }
    const form = new FormData(); form.append('language', language); form.append('source_url', mode === 'youtube' ? url : '')
    form.append('include_visuals', mode === 'upload' && visuals ? 'true' : 'false')
    if (mode === 'upload' && file) form.append('media', file)
    try {
      const response = await fetch(`${API}/api/jobs`, { method: 'POST', body: form })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || 'Could not start analysis.')
      setBatchJobs([]); localStorage.removeItem(BATCH_JOBS_KEY); setJobId(data.job_id); localStorage.setItem(ACTIVE_JOB_KEY, data.job_id); setJob({ state: 'queued', steps: {} })
    } catch (err) { setError(err.message || 'Could not reach the FrameSutra API.') }
  }

  async function sendQuestion(event) {
    event.preventDefault(); if (!question.trim() || sending) return
    const asked = question.trim(); setQuestion(''); setChat(items => [...items, { role: 'user', text: asked }]); setSending(true)
    try {
      const response = await fetch(`${API}/api/jobs/${jobId}/chat`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ question: asked }) })
      const data = await response.json(); if (!response.ok) throw new Error(data.detail || 'Answer unavailable.')
      setChat(items => [...items, { role: 'assistant', text: data.answer, sources: data.sources || [] }])
    } catch (err) { setChat(items => [...items, { role: 'assistant', text: err.message }]) }
    finally { setSending(false) }
  }

  async function openLibraryJob(id) {
    const response = await fetch(`${API}/api/jobs/${id}`); const data = await response.json()
    if (!response.ok) { setError(data.detail || 'Could not open this analysis.'); return }
    setBatchJobs([]); localStorage.removeItem(BATCH_JOBS_KEY); setJobId(id); localStorage.setItem(ACTIVE_JOB_KEY, id); setJob(data); setPage('workspace'); setTab('Overview')
    const messages = await fetch(`${API}/api/jobs/${id}/chat`).then(r => r.ok ? r.json() : []).catch(() => [])
    setChat(messages.map(m => ({ role: m.role, text: m.content, sources: m.sources || [] })))
  }
  async function openBatchJob(id) {
    const response = await fetch(`${API}/api/jobs/${id}`); const data = await response.json()
    if (!response.ok) { setError(data.detail || 'Could not open this batch item.'); return }
    setJobId(id); localStorage.setItem(ACTIVE_JOB_KEY, id); setJob(data); setPage('workspace'); setTab('Overview')
    const messages = await fetch(`${API}/api/jobs/${id}/chat`).then(r => r.ok ? r.json() : []).catch(() => [])
    setChat(messages.map(m => ({ role: m.role, text: m.content, sources: m.sources || [] })))
  }
  async function deleteLibraryJob(id) {
    if (!window.confirm('Delete this analysis and its local files? This cannot be undone.')) return
    const response = await fetch(`${API}/api/jobs/${id}`, { method: 'DELETE' }); if (response.ok) setLibraryItems(items => items.filter(item => item.id !== id))
    if (id === jobId) { setJob(null); setJobId(''); localStorage.removeItem(ACTIVE_JOB_KEY) }
  }
  async function toggleSaved(id, saved) {
    const response = await fetch(`${API}/api/jobs/${id}/saved`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ saved }) })
    if (response.ok) setLibraryItems(items => items.map(item => item.id === id ? { ...item, saved } : item))
  }
  async function retryJob(id) {
    const response = await fetch(`${API}/api/jobs/${id}/retry`, { method: 'POST' }); const data = await response.json()
    if (!response.ok) { setError(data.detail || 'Could not retry this analysis.'); return }
    setJobId(data.job_id); localStorage.setItem(ACTIVE_JOB_KEY, data.job_id); setJob({ state: 'queued', steps: {} }); setPage('workspace')
  }
  async function refreshTimestamps(id) {
    setError('')
    const response = await fetch(`${API}/api/jobs/${id}/retimestamp`, { method:'POST' }); const data = await response.json()
    if (!response.ok) { setError(data.detail || 'Could not refresh the timestamps.'); return }
    setBatchJobs([]); localStorage.removeItem(BATCH_JOBS_KEY); setJobId(data.job_id); localStorage.setItem(ACTIVE_JOB_KEY, data.job_id); setJob({ state:'queued', steps:{} }); setPage('workspace')
  }
  async function resetCache() {
    if (!window.confirm('Clear transcript, analysis, visual and YouTube audio caches? Saved analysis results will remain.')) return
    const response = await fetch(`${API}/api/cache`, { method: 'DELETE', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ confirm: true }) })
    const data = await response.json(); if (!response.ok) setSystemError(data.detail || 'Could not clear caches'); else { setSystemError(''); setSystemMetrics(m => m ? { ...m, cache_clear: data.cleared_files } : m) }
  }
  async function runManualCleanup() {
    const response = await fetch(`${API}/api/maintenance/cleanup`, { method: 'POST' }); const data = await response.json()
    if (!response.ok) setSystemError(data.detail || 'Cleanup failed'); else { setSystemError(`Cleanup complete: ${data.expired_jobs} expired analyses, ${data.removed_media_files} media files, ${data.removed_cache_files} cache files removed.`); setSystemMetrics(m => m ? { ...m, last_cleanup: data } : m) }
  }
  function reset() { setJobId(''); localStorage.removeItem(ACTIVE_JOB_KEY); setJob(null); setBatchJobs([]); localStorage.removeItem(BATCH_JOBS_KEY); setPage('workspace'); setError(''); setUrl(''); setFile(null); setChat([]); setTab('Overview') }

  if (isNotFound) return <><CursorAura/><NotFound theme={theme} onToggleTheme={() => setTheme(value => value === 'light' ? 'dark' : 'light')} /></>

  return <div className="app-shell">
    <CursorAura />
    <header className="topbar">
      <a className="brand" href="#home" onClick={reset}><span className="brand-icon framesutra-mark"><img src="/framesutra-mark.png" alt="" /></span><span>Frame<span className="brand-accent">Sutra</span><small>AI VIDEO UNDERSTANDING</small></span></a>
      <nav className={`top-links ${menuOpen ? 'menu-open' : ''}`}><button onClick={() => {reset();setMenuOpen(false)}}>Workspace</button><button onClick={() => {setPage('library');setMenuOpen(false)}}>Analysis library</button><button onClick={() => {setPage('system');setMenuOpen(false)}}>System</button><button onClick={() => {setLegalPage('How to use');setMenuOpen(false)}}>How to use</button><span className="privacy"><span /> Local-first processing</span></nav>
      <button className="mobile-menu-button" aria-label="Toggle navigation" aria-expanded={menuOpen} onClick={() => setMenuOpen(open => !open)}><Menu size={18}/></button>
      <ThemeToggle theme={theme} onToggle={() => setTheme(value => value === 'light' ? 'dark' : 'light')} />
      <button className="button button-dark top-cta" onClick={() => { setMenuOpen(false); if (page !== 'workspace') reset(); setTimeout(() => inputRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' }), 30) }}><Plus size={16}/> New analysis</button>
    </header>

    <main>
      {page === 'library' ? <Library items={libraryItems} query={libraryQuery} setQuery={setLibraryQuery} loading={libraryLoading} onOpen={openLibraryJob} onDelete={deleteLibraryJob} onSave={toggleSaved} onRetry={retryJob}/>
      : page === 'system' ? <SystemDashboard metrics={systemMetrics} error={systemError} onClearCache={resetCache} onCleanup={runManualCleanup}/>
      : !results && !busy && !['error','interrupted','cancelled'].includes(job?.state) ? <>
        <section className="hero" id="home">
          <div className="hero-copy"><div className="eyebrow"><span className="sparkle"><Sparkles size={13}/></span> YOUR VIDEO KNOWLEDGE DESK</div>
            <h1>Every frame has a story.<br/>Every word has an <em>answer.</em></h1>
            <p>FrameSutra brings transcription, summaries and source-grounded answers together in one local-first video workspace.</p>
            <div className="hero-points"><span><Check size={14}/> Structured summaries</span><span><Check size={14}/> Searchable transcript</span><span><Check size={14}/> Grounded AI answers</span></div>
          </div>
          <div className="hero-art" aria-hidden="true"><div className="art-orbit orbit-one"/><div className="art-orbit orbit-two"/><div className="art-card"><div className="art-window"><span/><span/><span/></div><div className="waveform">{Array.from({length: 36}, (_, i) => <i key={i} style={{'--h': `${12 + ((i * 17 + i * i * 3) % 50)}px`}} />)}</div><div className="art-label"><span className="pulse"/> TRANSCRIPT READY <b>04:32</b></div></div><div className="art-chip chip-a"><AudioLines size={15}/> Whisper transcription</div><div className="art-chip chip-b"><Sparkles size={15}/> AI notes</div><div className="art-dot dot-a"/><div className="art-dot dot-b"/></div>
        </section>

        <section className="workspace" id="workspace" ref={inputRef}>
          <div className="workspace-heading"><div><div className="eyebrow">START A WORKSPACE</div><h2>Bring in a video</h2><p>Start from a public YouTube link or upload a local recording.</p></div><div className="step-count"><span>01</span><i/><span>02</span><i/><span>03</span></div></div>
          <form className="source-card" onSubmit={startAnalysis}>
            <div className="source-tabs"><button type="button" className={mode === 'youtube' ? 'selected' : ''} onClick={() => setMode('youtube')}><Link2 size={16}/> YouTube link</button><button type="button" className={mode === 'upload' ? 'selected' : ''} onClick={() => setMode('upload')}><Upload size={16}/> Upload a file</button><button type="button" className={mode === 'batch' ? 'selected' : ''} onClick={() => setMode('batch')}><Layers size={16}/> Batch</button></div>
            <div className="form-content">
              {mode === 'youtube' ? <label className="field-label">VIDEO URL<div className="url-field"><Link2 size={17}/><input required type="url" placeholder="https://youtube.com/watch?v=..." value={url} onChange={e => setUrl(e.target.value)}/><span>PUBLIC VIDEO</span></div></label> : mode === 'upload' ? <label className={`dropzone ${file ? 'has-file' : ''}`}><input type="file" accept="video/*,audio/*,.mkv,.m4a,.flac,.ogg" onChange={e => setFile(e.target.files?.[0] || null)}/>{file ? <><span className="drop-icon"><FileAudio2 size={20}/></span><b>{file.name}</b><small>{(file.size / 1024 / 1024).toFixed(1)} MB · Ready to analyze</small></> : <><span className="drop-icon"><Upload size={20}/></span><b>Drop your video or audio here</b><small>or <u>browse files</u> · MP4, MOV, MP3, WAV and more</small></>}</label> : <div className="batch-inputs"><label className="field-label">YOUTUBE LINKS · ONE PER LINE<textarea rows="3" placeholder="https://youtube.com/watch?v=..." value={batchUrls} onChange={e => setBatchUrls(e.target.value)}/></label><label className="batch-file-label"><Upload size={15}/> Add local files<input type="file" multiple accept="video/*,audio/*,.mkv,.m4a,.flac,.ogg" onChange={e => setBatchFiles(Array.from(e.target.files || []).slice(0,3))}/><small>{batchFiles.map(x => x.name).join(' · ') || 'No files selected'}</small></label><small className="batch-limit">{batchUrls.split(/\r?\n/).filter(x => x.trim()).length + batchFiles.length}/3 sources selected · batch is capped at three.</small></div>}
              <div className="form-options"><label className="field-label lang-label">SPEECH LANGUAGE<select value={language} onChange={e => setLanguage(e.target.value)}><option value="english">English · Local Whisper</option><option value="hinglish">Hinglish · Sarvam AI</option></select></label>{mode !== 'youtube' && <label className="visual-option"><input type="checkbox" checked={visuals} onChange={e => setVisuals(e.target.checked)}/><span className="check-ui"><Check size={12}/></span><span><b>Analyze video frames</b><small>Optional visual notes · local videos</small></span></label>}</div>
              <div className="agreement-check"><input id="user-agreement" type="checkbox" required checked={agreementAccepted} onChange={e => setAgreementAccepted(e.target.checked)}/><label htmlFor="user-agreement">I agree to the</label><button type="button" onClick={() => setLegalPage('User agreement')}>User Agreement</button><span>and have read the</span><button type="button" onClick={() => setLegalPage('Privacy policy')}>Privacy Policy</button>.</div>
              {error && <div className="error-box"><CircleHelp size={17}/><span>{error}</span></div>}
              <button className="button button-primary submit-button" type="submit" disabled={busy || (mode === 'upload' && !file) || (mode === 'batch' && !batchUrls.trim() && !batchFiles.length)}>{busy ? <><LoaderCircle className="spin" size={17}/> Starting analysis…</> : <>{mode === 'batch' ? 'Queue batch' : 'Analyze video'} <ArrowRight size={17}/></>}</button>
              <p className="form-footnote"><Globe2 size={13}/> English transcription runs locally. Default limits: 512 MB, six hours, three active or queued jobs.</p>
            </div>
          </form>
        </section>

        <section className="steps-section" id="workflow"><div className="eyebrow">FROM RECORDING TO INSIGHT</div><h2>A focused workflow, end to end.</h2><div className="feature-row"><article><span className="feature-icon"><AudioLines size={19}/></span><div><b>1. Add a source</b><p>Paste a public YouTube URL, upload a local audio or video file, or queue up to three sources.</p></div><span className="feature-index">01</span></article><article><span className="feature-icon blue"><WandSparkles size={19}/></span><div><b>2. Review the analysis</b><p>Follow transcription and analysis progress. Explore summaries, decisions, chapters and optional visual notes.</p></div><span className="feature-index">02</span></article><article><span className="feature-icon violet"><Search size={19}/></span><div><b>3. Ask, save and export</b><p>Ask transcript-grounded questions, save useful analyses, and export notes or transcripts.</p></div><span className="feature-index">03</span></article></div><button className="text-button guide-link" onClick={() => setLegalPage('How to use')}>Read the full usage guide <ChevronRight size={13}/></button></section>
      </> : busy ? <Processing job={job} batchJobs={batchJobs} onSelect={openBatchJob} onBack={reset} onCancel={async () => { await fetch(`${API}/api/jobs/${jobId}/cancel`, { method: 'POST' }); const response = await fetch(`${API}/api/jobs/${jobId}`); if (response.ok) setJob(await response.json()) }}/> : ['error','interrupted','cancelled'].includes(job?.state) ? <Failure message={job.error} onBack={reset} onRetry={job.retry_available ? () => retryJob(job.id) : null}/> : <Results job={job} batchJobs={batchJobs} onSelectBatch={openBatchJob} onRetimestamp={refreshTimestamps} error={error} tab={tab} setTab={setTab} chat={chat} setChat={setChat} question={question} setQuestion={setQuestion} onAsk={sendQuestion} sending={sending} onNew={reset} words={transcriptWords}/>}
    </main>
    <footer className="site-footer"><div className="footer-main"><a className="brand footer-brand" href="#home" onClick={reset}><span className="brand-icon framesutra-mark"><img src="/framesutra-mark.png" alt="" /></span><span>Frame<span className="brand-accent">Sutra</span></span></a><p>FrameSutra turns long recordings into searchable transcripts, structured notes and source-grounded answers. Designed as a local-first video understanding workspace.</p><span className="footer-owner">Built with effort by Akarsh Mishra</span></div><div className="footer-links"><b>Explore</b><button onClick={() => setLegalPage('How to use')}>How to use</button><button onClick={() => setLegalPage('About FrameSutra')}>About FrameSutra</button></div><div className="footer-links"><b>Policies</b><button onClick={() => setLegalPage('Terms & conditions')}>Terms &amp; conditions</button><button onClick={() => setLegalPage('Privacy policy')}>Privacy policy</button><button onClick={() => setLegalPage('User agreement')}>User agreement</button></div><div className="footer-bottom"><span>Every frame has a story. Every word has an answer.</span><span>© {new Date().getFullYear()} FrameSutra</span></div></footer>
    {legalPage && <LegalDialog title={legalPage} onClose={() => setLegalPage('')}/>}
  </div>
}

function NotFound({ theme, onToggleTheme }) {
  return <main className="not-found-page">
    <div className="not-found-tools"><ThemeToggle theme={theme} onToggle={onToggleTheme}/></div>
    <div className="not-found-glow" aria-hidden="true" />
    <div className="not-found-card">
      <div className="not-found-game" aria-hidden="true"><Gamepad2 size={43} strokeWidth={1.5}/><span>✦</span></div>
      <div className="eyebrow"><span className="sparkle"><Sparkles size={13}/></span> LOST IN THE FOOTAGE?</div>
      <h1>404<span>.</span></h1>
      <h2>This frame is missing.</h2>
      <p>The page you’re looking for may have moved, or the link may be incomplete. Let’s get you back to your video workspace.</p>
      <a className="button button-primary not-found-home" href="/" onClick={event => { event.preventDefault(); window.location.assign('/') }}><ArrowLeft size={16}/> Back to FrameSutra</a>
      <small>FRAMESUTRA · AI VIDEO UNDERSTANDING</small>
    </div>
  </main>
}

function Processing({ job, batchJobs, onSelect, onBack, onCancel }) {
  return <section className="processing-page"><button className="back-link" onClick={onBack}><ArrowLeft size={15}/> Change source</button>{batchJobs.length > 1 && <div className="batch-progress"><b>Batch progress · {batchJobs.filter(item => item.state === 'complete').length}/{batchJobs.length} complete</b>{batchJobs.map((item,index)=><button key={item.id} className={item.id===job.id?'active':''} onClick={()=>onSelect(item.id)}><span>{String(index+1).padStart(2,'0')}</span><b>Video {index+1}</b><small>{item.steps?.transcript?.detail || item.state}</small><em>{item.state}</em></button>)}</div>}<div className="processing-heading"><div className="processing-icon"><LoaderCircle className="spin" size={22}/></div><div><div className="eyebrow">YOUR WORKSPACE IS IN PROGRESS</div><h1>{job?.state === 'queued' ? 'In the queue.' : 'Listening closely.'}</h1><p>We’re preparing the recording and turning it into searchable knowledge.</p></div></div><div className="pipeline-card"><div className="pipeline-top"><div><b>Analysis pipeline</b><small>Stages update as each part completes</small></div><span className="live-pill"><i/> {job?.state === 'queued' ? 'QUEUED' : 'LIVE'}</span></div><div className="pipeline-list">{stages.map(([key, label], i) => { const state = job?.steps?.[key]?.state || 'pending'; return <div className={`pipeline-stage ${state}`} key={key}><span className="stage-mark">{state === 'done' || state === 'skipped' ? <Check size={13}/> : state === 'active' ? <LoaderCircle className="spin" size={14}/> : <span>{String(i + 1).padStart(2, '0')}</span>}</span><div><b>{label}</b><small>{job?.steps?.[key]?.detail || (state === 'done' ? `Completed · ${job?.stage_times?.[key] || 0}s` : state === 'skipped' ? 'Skipped for this source' : state === 'active' ? 'Working on this step now' : 'Waiting')}</small></div><span className="stage-state">{state === 'active' ? 'IN PROGRESS' : state === 'done' ? 'DONE' : state === 'error' ? 'ERROR' : ''}</span></div>})}</div><div className="pipeline-note"><Clock3 size={15}/> Longer recordings may take a while, especially on the first run while models load.<button className="cancel-job" onClick={onCancel}><X size={13}/> Cancel job</button></div></div></section>
}

function Failure({ message, onBack, onRetry }) {
  return <section className="processing-page"><button className="back-link" onClick={onBack}><ArrowLeft size={15}/> Change source</button><div className="failure-card"><span className="failure-icon"><CircleHelp size={22}/></span><div className="eyebrow">ANALYSIS NEEDS ATTENTION</div><h1>We couldn’t finish this run.</h1><p>{message || 'The analysis stopped unexpectedly. Check the API terminal for details, then try again.'}</p>{onRetry && <button className="button button-primary" onClick={onRetry}><RefreshCw size={15}/> Retry from checkpoint</button>}<button className="button button-light" onClick={onBack}><ArrowLeft size={15}/> Back to workspace</button></div></section>
}

function Results({ job, batchJobs, onSelectBatch, onRetimestamp, error, tab, setTab, chat, setChat, question, setQuestion, onAsk, sending, onNew, words }) {
  const r = job.result || {}
  const tabs = ['Overview', 'Chapters', 'Transcript', 'Visuals', 'Ask video', 'Study']
  const metrics = [[<Clock3/>, 'AUDIO CHUNKS', r.chunk_count || 0], [<FileText/>, 'TRANSCRIPT WORDS', words.toLocaleString()], [<Film/>, 'VISUAL FRAMES', r.visual_evidence?.length || 0]]
  const [bookmarks, setBookmarks] = useState([])
  const [bookmarkNote, setBookmarkNote] = useState('')
  const [bookmarkTime, setBookmarkTime] = useState('00:00:00')
  const [transcriptQuery, setTranscriptQuery] = useState('')
  const [chapters, setChapters] = useState(r.chapters || [])
  const [studyKind, setStudyKind] = useState('flashcards')
  const [studyData, setStudyData] = useState(null)
  const [studyLoading, setStudyLoading] = useState(false)
  const [quizHistory, setQuizHistory] = useState([])
  const [pdfLoading, setPdfLoading] = useState(false)
  const [pdfError, setPdfError] = useState('')
  const [saved, setSaved] = useState(Boolean(job.saved))
  const audioRefs = useRef([])
  const segments = useMemo(() => parseTranscript(r.transcript || ''), [r.transcript])
  const visibleSegments = useMemo(() => segments.filter(s => !transcriptQuery || s.text.toLowerCase().includes(transcriptQuery.toLowerCase())), [segments, transcriptQuery])
  const jsonReport = JSON.stringify({ title:r.title, source:r.source, language:r.language, summary:r.summary, action_items:r.action_items, key_decisions:r.key_decisions, open_questions:r.open_questions, transcript:r.transcript, chapters, bookmarks, visual_evidence:r.visual_evidence }, null, 2)
  const report = `# ${r.title || 'Video analysis'}\n\nSource: ${r.source || ''}\nLanguage: ${r.language || ''}\n\n## Summary\n\n${r.summary || ''}\n\n## Action items\n\n${r.action_items || ''}\n\n## Key decisions\n\n${r.key_decisions || ''}\n\n## Open questions\n\n${r.open_questions || ''}\n\n## Chapters\n\n${chapters.map(x=>`- ${x.timestamp} — ${x.title}`).join('\n')}\n\n## Bookmarks\n\n${bookmarks.map(x=>`- ${x.timestamp}${x.note?` — ${x.note}`:''}`).join('\n')}\n`
  const timeToSeconds = value => { const [h=0,m=0,s=0] = value.split(':').map(Number); return h*3600+m*60+s }
  const playAt = timestamp => {
    if (!/^\d{2}:\d{2}:\d{2}$/.test(timestamp || '')) { setTab('Transcript'); return }
    const seconds = timeToSeconds(timestamp)
    const index = Math.min(Math.floor(seconds / 600), Math.max(0, (r.audio_chunks?.length || 1) - 1))
    const player = audioRefs.current[index]
    if (player) { player.currentTime = seconds % 600; player.play().catch(() => {}) }
    setBookmarkTime(timestamp)
    setTab('Transcript')
  }
  useEffect(() => {
    fetch(`${API}/api/jobs/${job.id}/bookmarks`).then(x => x.ok ? x.json() : []).then(setBookmarks).catch(() => {})
    fetch(`${API}/api/jobs/${job.id}/chat`).then(x => x.ok ? x.json() : []).then(data => setChat(data.map(m => ({role:m.role,text:m.content,sources:m.sources || []})))).catch(() => {})
    setChapters(r.chapters || [])
    setSaved(Boolean(job.saved))
    setQuizHistory([])
  }, [job.id])
  useEffect(() => { setStudyData(null) }, [job.id, studyKind])
  async function addBookmark(event) {
    event.preventDefault()
    const response = await fetch(`${API}/api/jobs/${job.id}/bookmarks`, { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({timestamp:bookmarkTime,note:bookmarkNote}) })
    const data=await response.json(); if(response.ok){setBookmarks(items=>[...items,data].sort((a,b)=>a.timestamp.localeCompare(b.timestamp)));setBookmarkNote('')}
  }
  async function removeBookmark(id) { const response=await fetch(`${API}/api/jobs/${job.id}/bookmarks/${id}`,{method:'DELETE'});if(response.ok)setBookmarks(items=>items.filter(x=>x.id!==id)) }
  async function saveChapter(index, title) {
    const response=await fetch(`${API}/api/jobs/${job.id}/chapters/${index}`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({title})})
    if(response.ok){const data=await response.json();setChapters(items=>items.map((item,i)=>i===index?data:item))}
  }
  async function loadStudy() {
    setStudyLoading(true)
    try {
      let data
      if (studyKind === 'quiz') {
        const previousQuestions = quizHistory.flatMap(items => items.map(item => item.question))
        const response = await fetch(`${API}/api/jobs/${job.id}/study/quiz`, { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({previous_questions:previousQuestions}) })
        data = await response.json(); if (!response.ok) throw new Error(data.detail || 'Quiz generation failed')
        setQuizHistory(items => [...items, data.items].slice(-10))
      } else {
        let response = await fetch(`${API}/api/jobs/${job.id}/study/${studyKind}`); data = response.ok ? await response.json() : null
        if (!data) { response = await fetch(`${API}/api/jobs/${job.id}/study/${studyKind}`,{method:'POST'}); data = await response.json(); if (!response.ok) throw new Error(data.detail || 'Study generation failed') }
      }
      setStudyData(data)
    } catch(err){setStudyData({error:err.message})} finally{setStudyLoading(false)}
  }
  async function downloadPdfNotes() {
    setPdfLoading(true); setPdfError('')
    try {
      const response = await fetch(`${API}/api/jobs/${job.id}/export/pdf`)
      if (!response.ok) { const detail = await response.json().catch(() => ({})); throw new Error(detail.detail || 'Could not create PDF notes.') }
      const blob = await response.blob(); const objectUrl = URL.createObjectURL(blob); const link = document.createElement('a')
    link.href = objectUrl; link.download = `${safeName(r.title)}_video-notes.pdf`; link.click(); setTimeout(() => URL.revokeObjectURL(objectUrl), 1000)
    } catch (error) { setPdfError(error.message || 'Could not create PDF notes.') }
    finally { setPdfLoading(false) }
  }
  const toggleSave = async () => { const response=await fetch(`${API}/api/jobs/${job.id}/saved`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({saved:!saved})}); if(response.ok){const data=await response.json();setSaved(data.saved)} }
  return <section className="results-page">{batchJobs.length > 1 && <div className="batch-progress"><b>Batch progress - {batchJobs.filter(item => item.state === 'complete').length}/{batchJobs.length} complete</b>{batchJobs.map((item,index)=><button key={item.id} className={item.id===job.id?'active':''} onClick={()=>onSelectBatch(item.id)}><span>{String(index+1).padStart(2,'0')}</span><b>Video {index+1}</b><small>{item.steps?.transcript?.detail || item.state}</small><em>{item.state}</em></button>)}</div>}<div className="results-toolbar"><button className="back-link" onClick={onNew}><ArrowLeft size={15}/> All analyses</button><div className="toolbar-actions"><button className={`button ${saved?'button-saved':'button-light'}`} onClick={toggleSave}><Star size={14} fill={saved?'currentColor':'none'}/>{saved?'Saved':'Save to library'}</button>{r.language === 'english' && r.timestamp_quality !== 'Whisper speech segments' && <button className="button button-light" title="Re-run local Whisper on the retained audio to improve timestamps" onClick={()=>onRetimestamp(job.id)}>Refresh timestamps</button>}<button className="button button-primary" title="Includes the full transcript and generated review Q&A; uses one extra model request" disabled={pdfLoading} onClick={downloadPdfNotes}><ArrowDownToLine size={14}/>{pdfLoading?'Creating PDF...':'Colorful PDF notes'}</button><button className="button button-light" onClick={() => downloadText(r.transcript || '', `${safeName(r.title)}_transcript.txt`)}><ArrowDownToLine size={15}/> Export transcript</button></div></div>{error&&<div className="error-box">{error}</div>}{pdfError&&<div className="error-box">{pdfError}</div>}<div className="result-title-row"><div><div className="eyebrow"><span className="ready-dot"/> ANALYSIS COMPLETE</div><h1>{r.title || 'Video analysis'}</h1><p>{r.source} <span>·</span> {r.language === 'hinglish' ? 'Hinglish' : 'English'} transcription</p></div><button className="button button-primary" onClick={onNew}><Plus size={16}/> New analysis</button></div>
    {r.used_fallback && <div className="notice"><CircleHelp size={17}/> AI analysis used a transcript-based fallback. You can still review the transcript and ask grounded questions.</div>}
    <div className="metric-row">{metrics.map(([icon, label, value])=><div className="result-metric" key={label}><span>{icon}</span><small>{label}</small><b>{value}</b></div>)}</div>
    <div className="result-tabs">{tabs.map(t=><button key={t} className={tab === t ? 'active' : ''} onClick={() => setTab(t)}>{t === 'Overview' ? <Sparkles size={15}/> : t === 'Transcript' ? <FileText size={15}/> : t === 'Visuals' ? <Film size={15}/> : t === 'Chapters' ? <ListVideoIcon/> : t === 'Study' ? <BookOpen size={15}/> : <MessageSquareText size={15}/>} {t}</button>)}<span className="tab-spacer"/><button className="export-link" onClick={()=>downloadText(report, `${safeName(r.title)}_report.md`)}>MD</button><button className="export-link" onClick={()=>downloadText(jsonReport, `${safeName(r.title)}_report.json`)}>JSON</button></div>
    {tab === 'Overview' && <div className="overview-grid"><article className="content-panel summary-panel"><div className="panel-heading"><span className="panel-icon"><Sparkles size={16}/></span><div><b>Executive summary</b><small>The story in a few clear points</small></div></div><div className="prose">{r.summary || 'No summary available.'}</div></article><aside className="content-panel insight-panel"><div className="panel-heading"><span className="panel-icon coral"><WandSparkles size={16}/></span><div><b>Key takeaways</b><small>From this recording</small></div></div><Insight label="Action items" text={r.action_items}/><Insight label="Key decisions" text={r.key_decisions}/><Insight label="Open questions" text={r.open_questions}/></aside><div className="content-panel bookmark-panel"><div className="panel-heading"><span className="panel-icon purple"><Bookmark size={15}/></span><div><b>Bookmarks</b><small>Saved timestamps and notes</small></div></div><BookmarkEditor time={bookmarkTime} setTime={setBookmarkTime} note={bookmarkNote} setNote={setBookmarkNote} onAdd={addBookmark} items={bookmarks} onPlay={playAt} onDelete={removeBookmark}/></div></div>}
    {tab === 'Chapters' && <div className="chapter-list">{chapters.length ? chapters.map((chapter,i)=><article className="content-panel chapter-item" key={i}><button className="chapter-time" onClick={()=>playAt(chapter.timestamp)}><Play size={13} fill="currentColor"/>{chapter.timestamp}</button><label><small>EDITABLE CHAPTER TITLE</small><input defaultValue={chapter.title} key={`${i}-${chapter.title}`} maxLength={120} onBlur={e=>{if(e.target.value.trim()&&e.target.value!==chapter.title)saveChapter(i,e.target.value.trim())}} onKeyDown={e=>{if(e.key==='Enter')e.currentTarget.blur()}}/></label><span className="chapter-number">{String(i+1).padStart(2,'0')}</span></article>) : <Empty icon={<BookOpen/>} title="No timestamped chapters" text="Chapters use the transcript's approximate ten-minute segment markers."/>}</div>}
    {tab === 'Transcript' && <article className="content-panel transcript-panel"><div className="panel-heading"><span className="panel-icon"><FileText size={16}/></span><div><b>Searchable transcript</b><small>{words.toLocaleString()} words · {r.timestamp_quality || 'Approximate 10-minute segment starts'}</small></div><button className="mini-button" onClick={() => downloadText(r.transcript || '', `${safeName(r.title)}_transcript.txt`)}><ArrowDownToLine size={15}/></button></div><label className="transcript-search"><Search size={15}/><input value={transcriptQuery} onChange={e=>setTranscriptQuery(e.target.value)} placeholder="Search words or phrases in this transcript…"/><span>{visibleSegments.length} segments</span></label>{r.audio_chunks?.length > 0 && <div className="audio-list"><div className="audio-list-title"><AudioLines size={14}/> Processed audio <small>{r.audio_chunks.length} segment{r.audio_chunks.length === 1 ? '' : 's'}</small></div>{r.audio_chunks.map((_, i)=><div className="audio-row" key={i}><span>Segment {String(i + 1).padStart(2, '0')}</span><audio ref={el=>audioRefs.current[i]=el} controls preload="none" src={`${API}/api/jobs/${job.id}/audio/${i}`}>Audio playback is not supported by this browser.</audio></div>)}</div>}<div className="transcript-segments">{visibleSegments.map((segment,i)=><article key={segment.timestamp} className="transcript-segment"><button className="segment-timestamp" onClick={()=>playAt(segment.timestamp)}><Play size={12} fill="currentColor"/>{segment.timestamp}</button><p>{segment.text}</p><button className="segment-bookmark" title="Bookmark this section" onClick={()=>{setBookmarkTime(segment.timestamp);setBookmarkNote('');setTab('Overview')}}><Bookmark size={13}/></button></article>)}{!visibleSegments.length&&<div className="empty-state"><Search/><b>No matching transcript sections</b><p>Try a shorter or different search term.</p></div>}</div></article>}
    {tab === 'Visuals' && <div className="visual-list">{r.visual_evidence?.length ? r.visual_evidence.map((item, i)=><article className="content-panel visual-item" key={i}><button className="visual-time" onClick={()=>playAt(item.timestamp)}><Film size={15}/> {item.timestamp}</button><p>{item.description}</p></article>) : <Empty icon={<Video/>} title="No visual notes yet" text="Visual frame analysis is available for uploaded local videos when enabled before processing."/>}</div>}
    {tab === 'Ask video' && <article className="content-panel chat-panel"><div className="panel-heading"><span className="panel-icon purple"><MessageSquareText size={16}/></span><div><b>Ask your video</b><small>Answers include transcript excerpts and approximate timestamps</small></div></div><div className="chat-messages">{!chat.length && <div className="chat-empty"><Sparkles size={20}/><b>What would you like to know?</b><span>Ask about an idea, a decision, or where a topic came up.</span><div className="suggestions">{['What are the main ideas?', 'List the action items', 'Explain the key decision'].map(q=><button key={q} onClick={()=>setQuestion(q)}>{q}<ChevronRight size={13}/></button>)}</div></div>}{chat.map((m,i)=><div className={`chat-message ${m.role}`} key={i}><span>{m.role === 'user' ? 'YOU' : 'FRAMESUTRA'}</span><p>{m.text}</p>{m.role==='assistant'&&m.sources?.length>0&&<div className="citation-list">{m.sources.map((source,index)=><button className="citation" key={index} onClick={()=>playAt(source.timestamp)}><span><Play size={10} fill="currentColor"/> {source.timestamp}</span><small>{source.excerpt}</small></button>)}</div>}</div>)}{sending && <div className="chat-message assistant"><span>FRAMESUTRA</span><p><LoaderCircle size={15} className="spin"/> Searching the transcript…</p></div>}</div><form className="chat-input" onSubmit={onAsk}><input value={question} onChange={e=>setQuestion(e.target.value)} placeholder="Ask something about this video…"/><button aria-label="Send question" disabled={sending || !question.trim()}><Send size={16}/></button></form><div className="grounding-note"><Search size={13}/> Search uses relevant transcript sections from your video.</div></article>}
    {tab === 'Study' && <StudyPanel jobId={job.id} kind={studyKind} setKind={setStudyKind} data={studyData} loading={studyLoading} onGenerate={loadStudy}/>}
  </section>
}

function ListVideoIcon(){return <Layers size={15}/>}
function parseTranscript(transcript){const re=/\[(?:Speech timestamp |Approx\. timestamp )(\d{2}:\d{2}:\d{2})\]\s*/g;const marks=[...transcript.matchAll(re)];const segments=marks.map((m,i)=>({timestamp:m[1],text:transcript.slice(m.index+m[0].length,i+1<marks.length?marks[i+1].index:transcript.length).trim()})).filter(x=>x.text);const grouped=[];for(const segment of segments){const seconds=segment.timestamp.split(':').reduce((total,part)=>total*60+Number(part),0);const last=grouped[grouped.length-1];if(!last||Math.floor(seconds/600)!==Math.floor(last.seconds/600)||last.text.length>=360){grouped.push({...segment,seconds})}else{last.text+=` ${segment.text}`}}return grouped}
function BookmarkEditor({time,setTime,note,setNote,onAdd,items,onPlay,onDelete}){return <><form className="bookmark-form" onSubmit={onAdd}><input aria-label="Bookmark timestamp" value={time} onChange={e=>setTime(e.target.value)} pattern="[0-9]{2}:[0-9]{2}:[0-9]{2}"/><input aria-label="Bookmark note" value={note} onChange={e=>setNote(e.target.value)} placeholder="Add a note (optional)"/><button className="button button-primary"><Plus size={13}/> Save</button></form><div className="bookmark-items">{items.length?items.map(item=><div className="bookmark-row" key={item.id}><button onClick={()=>onPlay(item.timestamp)}><Bookmark size={13}/><b>{item.timestamp}</b><span>{item.note||'Saved moment'}</span></button><button aria-label="Delete bookmark" onClick={()=>onDelete(item.id)}><X size={13}/></button></div>):<small className="muted-hint">No bookmarks yet. Add one from a transcript timestamp.</small>}</div></>}
function StudyPanel({jobId,kind,setKind,data,loading,onGenerate}) {
  const [revealed,setRevealed]=useState({})
  const [answers,setAnswers]=useState({})
  const [evaluation,setEvaluation]=useState(null)
  const [quizNotice,setQuizNotice]=useState('')
  const options=[['flashcards','Flashcards'],['quiz','Quiz'],['terms','Key terms']]
  const quizKey=data?.set_id || data?.items?.map(item=>item.question).join('|') || 'no-quiz'
  const evaluated=evaluation?.quizKey===quizKey
  const score=evaluated?evaluation.score:0
  const answeredCount=data?.items?.filter((_,index)=>answers[index]!==undefined).length||0
  const allAnswered=Boolean(data?.items?.length)&&answeredCount===data.items.length
  const canGenerate=kind!=='quiz'||!data?.items?.length||evaluated
  useEffect(()=>{setAnswers({});setEvaluation(null);setQuizNotice('');setRevealed({})},[quizKey])
  function evaluateQuiz(){
    if(!data?.items?.length)return
    if(!allAnswered){setQuizNotice('Please answer every question before evaluating.');return}
    const result=data.items.reduce((total,item,index)=>total+(Number(answers[index])===Number(item.answer_index)?1:0),0)
    setEvaluation({quizKey,score:result})
    setQuizNotice('')
  }
  return <div className="study-panel">
    <div className="study-intro"><span className="panel-icon violet"><BrainCircuit size={17}/></span><div><b>Study this video</b><small>{kind==='quiz'?'Fresh MCQ questions stay in browser memory for this session and are sent to your model to reduce repeats; the app does not save quiz sets.':'Flashcards and key terms are saved with this analysis.'}</small></div></div>
    <div className="study-controls">{options.map(([id,label])=><button type="button" key={id} className={kind===id?'selected':''} onClick={()=>setKind(id)}>{label}</button>)}<button type="button" className="button button-primary" disabled={loading||!canGenerate} onClick={onGenerate}>{loading?<><LoaderCircle className="spin" size={14}/> Generating</>:<><Sparkles size={14}/> {kind==='quiz'?(data?.items?.length?(evaluated?'Generate another quiz':'Quiz in progress'):'Generate quiz'):(data?'Load saved set':'Generate set')}</>}</button></div>
    {data?.error&&<div className="error-box">{data.error}</div>}
    {kind==='quiz'&&data?.items?.length>0&&<div className="quiz-workspace">
      <div className="quiz-set-heading"><div><b>Quiz set</b><small>Choose one answer for each question, then evaluate.</small></div><span>{answeredCount} / {data.items.length} answered</span></div>
      <div className="study-items">{data.items.map((item,i)=><article className="content-panel study-item quiz-question" key={`${quizKey}-${i}`}><small>QUESTION {String(i+1).padStart(2,'0')}</small><b>{item.question}</b><div className="quiz-choices">{item.choices?.map((choice,j)=>{const selected=Number(answers[i])===j;const resultClass=evaluated?(j===Number(item.answer_index)?'correct':selected?'incorrect':''):'';return <label className={`quiz-choice ${selected?'selected':''} ${resultClass}`} key={j}><input type="radio" name={`quiz-${quizKey}-${i}`} value={j} checked={selected} disabled={evaluated} onChange={()=>setAnswers(current=>({...current,[i]:j}))}/><span>{String.fromCharCode(65+j)}. {choice}</span></label>})}</div>{evaluated&&<p className="quiz-explanation"><b>{Number(answers[i])===Number(item.answer_index)?'Correct.':'Review:'}</b> {item.explanation}</p>}</article>)}</div>
      {!evaluated?<><button type="button" className="button button-primary quiz-evaluate" onClick={evaluateQuiz}>Evaluate answers</button>{!allAnswered&&!quizNotice&&<small className="quiz-progress-hint">Select an answer for all {data.items.length} questions. {answeredCount} answered so far.</small>}{quizNotice&&<div className="error-box" role="status">{quizNotice}</div>}</>:<div className="quiz-result" role="status"><b>Your score: {score} / {data.items.length}</b><span>{score===data.items.length?'Excellent work.':'Review the explanations, then try a new set.'}</span></div>}
    </div>}
    {data?.items?.length>0&&kind!=='quiz'&&<div className="study-items">{data.items.map((item,i)=><article className="content-panel study-item" key={i}>{kind==='flashcards'?<><small>FLASHCARD {String(i+1).padStart(2,'0')}</small><b>{item.front}</b><button type="button" className="text-button" onClick={()=>setRevealed(x=>({...x,[i]:!x[i]}))}>{revealed[i]?item.back:'Reveal answer'}</button></>:<><small>KEY TERM</small><b>{item.term}</b><p>{item.definition}</p></>}</article>)}</div>}
    {!data&&!loading&&<Empty icon={<BookOpen/>} title={kind==='quiz'?'Start a new quiz':'Make a review set'} text={kind==='quiz'?'Generate ten fresh multiple-choice questions from this transcript. Your recent questions are used only in memory to reduce repeats.':'Generate flashcards or a glossary from the transcript. These study sets are saved with the analysis.'}/>}
  </div>
}
function Library({items,query,setQuery,loading,onOpen,onDelete,onSave,onRetry}){
  const [filter,setFilter]=useState('all')
  const visible=items.filter(x=>filter==='all'||x.saved)
  return <section className="library-page"><div className="eyebrow"><Layers size={13}/> PERSONAL VIDEO LIBRARY</div><div className="library-heading"><div><h1>Your analyses.</h1><p>Search, reopen, save, export or remove your local video workspaces.</p></div><span className="library-count">{visible.length} {visible.length===1?'analysis':'analyses'}</span></div><div className="library-tools"><label className="library-search"><Search size={16}/><input value={query} onChange={e=>setQuery(e.target.value)} placeholder="Search titles and sources…"/><span>{loading?'Loading…':'LOCAL SQLITE'}</span></label><div className="library-filters"><button className={filter==='all'?'active':''} onClick={()=>setFilter('all')}>All</button><button className={filter==='saved'?'active':''} onClick={()=>setFilter('saved')}><Star size={13}/> Saved</button></div></div>{loading?<div className="library-empty"><LoaderCircle className="spin"/><span>Loading your library…</span></div>:visible.length?<div className="library-list">{visible.map(item=>{const result=item.result||{};const completed=Object.values(item.steps||{}).filter(x=>x.state==='done'||x.state==='skipped').length;return <article className="library-item" key={item.id}><button className="library-item-main" onClick={()=>onOpen(item.id)}><span className={`library-thumb ${item.state}`}><Video size={20}/></span><span className="library-item-copy"><b>{result.title||result.source||'Video analysis'}</b><small>{result.source||'Processing source'} · {result.language||'Language pending'} · {new Date(item.created_at).toLocaleString()}</small><span className={`status-label ${item.state}`}>{item.state==='complete'?'READY':item.state==='queued'?'QUEUED':item.state==='running'?`PROCESSING · ${completed}/7`:item.state.toUpperCase()}</span></span><ChevronRight size={17}/></button><div className="library-actions">{item.retry_available&&<button title="Retry from checkpoints" onClick={()=>onRetry(item.id)}><RefreshCw size={14}/></button>}<button className={item.saved?'is-saved':''} title={item.saved?'Remove from saved':'Save analysis'} onClick={()=>onSave(item.id,!item.saved)}><Star size={14} fill={item.saved?'currentColor':'none'}/></button><button className="delete-action" title="Delete analysis" onClick={()=>onDelete(item.id)}><Trash2 size={14}/></button></div></article>})}</div>:<div className="library-empty"><Layers size={24}/><b>{filter==='saved'?'No saved analyses yet':'Your library is empty'}</b><span>Completed and in-progress jobs will appear here. Save an analysis to keep it beyond the normal retention period.</span></div>}</section>
}

function SystemDashboard({metrics,error,onClearCache,onCleanup}){
  const jobs=metrics?.jobs||{};const disk=metrics?.disk||{};const gb=n=>(n/1024/1024/1024).toFixed(1)
  return <section className="system-page"><div className="eyebrow"><Settings2 size={13}/> LOCAL OPERATIONS</div><div className="library-heading"><div><h1>System health.</h1><p>Local queue, storage, provider counters and cache controls.</p></div><span className="live-pill"><i/> {metrics?'ONLINE':'CONNECTING'}</span></div>{error&&<div className="notice"><CircleHelp size={15}/>{error}</div>}<div className="system-grid"><article className="system-stat"><small>QUEUE</small><b>{jobs.queued_or_running??'—'} <span>/ {metrics?.queue_capacity??'—'}</span></b><p>{metrics?.workers??'—'} worker(s) · bounded admission</p></article><article className="system-stat"><small>COMPLETED</small><b>{jobs.completed??'—'}</b><p>Persisted analysis records</p></article><article className="system-stat"><small>FAILED / INTERRUPTED</small><b>{(jobs.failed??0)+(jobs.cancelled??0)}</b><p>Retry from saved checkpoints</p></article><article className="system-stat"><small>LOCAL DISK</small><b>{metrics?`${gb(disk.used)} GB`:'—'}</b><p>{metrics?`${gb(disk.free)} GB free of ${gb(disk.total)} GB`:'Checking disk use'}</p></article></div><div className="system-panels"><article className="content-panel"><div className="panel-heading"><span className="panel-icon"><RefreshCw size={15}/></span><div><b>Retention and cache</b><small>Automatic cleanup runs at startup and daily</small></div></div><p className="system-copy">Completed, failed, and interrupted records expire after {metrics?.retention_days||30} days unless saved. Media is retained for {metrics?.media_retention_days||7} days. Derived model checkpoints are retained locally for reuse.</p><div className="system-buttons"><button className="button button-light" onClick={onCleanup}><Trash2 size={14}/> Run cleanup now</button><button className="button button-light" onClick={onClearCache}><X size={14}/> Clear reusable caches</button></div></article><article className="content-panel"><div className="panel-heading"><span className="panel-icon coral"><BrainCircuit size={15}/></span><div><b>Provider activity</b><small>Process counters; reset when the API restarts</small></div></div><div className="counter-list">{Object.entries(metrics?.provider_counters||{}).map(([key,value])=><div key={key}><span>{key.replaceAll('_',' ')}</span><b>{value}</b></div>)}{!Object.keys(metrics?.provider_counters||{}).length&&<small className="muted-hint">No provider calls recorded in this API session.</small>}</div></article></div><p className="system-footnote">Media and indexes are stored on this machine. Keep this API private; rate limits and local IP ownership are intended for a single-user local setup.</p></section>
}

function LegalDialog({title,onClose}){
  useEffect(()=>{
    const closeOnEscape=event=>{if(event.key==='Escape')onClose()}
    window.addEventListener('keydown',closeOnEscape)
    return ()=>window.removeEventListener('keydown',closeOnEscape)
  },[onClose])
  const sections={
    'How to use':[
      ['1. Choose a source','Paste a public YouTube URL, upload an audio or video file, or use Batch to submit up to three sources. Follow the upload limits shown in the workspace. Only submit media you own or are allowed to use.'],
      ['2. Select options','Choose English transcription or Hinglish processing. For local uploads, enable frame analysis if you want visual notes. Frame analysis is optional and may take additional time.'],
      ['3. Follow the job','Keep the API running while a job processes. The progress page shows each pipeline step. You can cancel a running job, retry eligible interrupted jobs, or return to the workspace.'],
      ['4. Review and export','Open the overview, transcript, visuals, chapters, study tools or Ask video tabs. Transcript answers can be approximate; use timestamps to check important details in the source. Save work to the library and export available notes or transcript files.'],
      ['5. Manage saved data','Use Analysis library to reopen, save or delete individual jobs. System provides cache controls and cleanup. Unsaved jobs normally expire after 30 days and media files after 7 days; environment settings can change these periods.']
    ],
    'About FrameSutra':[
      ['The project','FrameSutra is an AI-powered video understanding workspace for lectures, tutorials, interviews, meetings and other long recordings. It combines transcription, summaries, visual insights and source-grounded answers in one local-first workflow.'],
      ['How it is built','The project includes a React interface, a local FastAPI service, Python processing components, a SQLite job library and a local vector index. English speech transcription and retrieval are processed on the host; configured provider APIs may be used for language and generative AI features.'],
      ['Project details','Project name: FrameSutra. Tagline: Every Frame Has a Story. Every Word Has an Answer. Built with effort by Akarsh Mishra.']
    ],
    'Privacy policy':[
      ['What is stored','Submitted media and generated working files may be stored in this project’s local uploads and downloads folders. Job details, transcripts, results, bookmarks and chat history may be stored in the local SQLite database; transcript search data may be held in the local vector index. Browser storage keeps the active job and batch identifiers.'],
      ['Where processing happens','The app is local-first, not fully offline. English transcription, file handling and retrieval run on the machine hosting the API. Analysis and chat may send transcript excerpts or prompts to the configured Groq service. Hinglish processing may send audio or transcript content to Sarvam when enabled. Review those providers’ terms before sending sensitive material.'],
      ['Retention and deletion','By default, completed job records expire after 30 days and media files after 7 days; saved items and local environment settings can change cleanup behavior. Use library deletion and System cleanup controls to remove data. Clearing caches is separate from deleting saved analyses. A full project reset also requires deleting local runtime folders and the SQLite database.'],
      ['Security and sharing','This project is designed for local, single-user use and does not provide account authentication. Do not expose the API to a public network without adding appropriate access controls. Anyone with access to the host or its files may be able to access stored data.'],
      ['Your choices','Do not submit confidential recordings unless you are authorized and have reviewed the configured providers’ data practices. You can stop a job, delete an analysis, clear caches, or stop using the app.']
    ],
    'Terms & conditions':[
      ['Acceptable use','Use FrameSutra lawfully and only with recordings, URLs and content you have the right to process. Respect copyright, privacy, consent, platform rules and any workplace or school policies that apply. Do not use the app to violate another person’s rights.'],
      ['Generated content','Transcription, summaries, chapters, classifications and AI answers can be incomplete or wrong. Check the original source before relying on them, especially for legal, medical, financial, safety or other consequential decisions. The app does not guarantee accuracy, availability or uninterrupted processing.'],
      ['Providers and changes','Some features rely on third-party AI services configured by the operator and are subject to those providers’ terms and availability. Project behavior, limits and retention settings may change with the software configuration.'],
      ['Project credit and contact','Built with effort by Akarsh Mishra. No business address, support contact, legal entity or governing jurisdiction has been supplied, so none is asserted here.']
    ],
    'User agreement':[
      ['By submitting a source','You confirm that you have the authority and permissions needed to process the linked or uploaded material. You understand that local files may be retained temporarily and that configured AI providers may receive content needed for enabled features.'],
      ['Your responsibilities','You are responsible for checking the generated output, protecting access to the host machine, complying with applicable laws and provider terms, and deleting data when it is no longer needed. Do not treat generated output as professional advice or a substitute for the original recording.'],
      ['Acknowledgement','Check the agreement box in the workspace before starting analysis. You can review this agreement and the privacy policy at any time from the footer.']
    ]
  }
  const content=sections[title]||sections['About FrameSutra']
  return <div className="legal-backdrop" role="presentation" onMouseDown={event=>{if(event.target===event.currentTarget)onClose()}}><section className="legal-dialog" role="dialog" aria-modal="true" aria-labelledby="legal-title"><header><div><div className="eyebrow">FRAMESUTRA · PROJECT INFORMATION</div><h2 id="legal-title">{title}</h2></div><button type="button" className="legal-close" aria-label="Close" onClick={onClose}><X size={18}/></button></header><div className="legal-content">{content.map(([heading,body])=><article key={heading}><h3>{heading}</h3><p>{body}</p></article>)}</div><div className="legal-updated">Project information · Review provider and local configuration before processing sensitive media.</div><button type="button" className="button button-primary legal-done" onClick={onClose}>Close</button></section></div>
}

function ThemeToggle({theme,onToggle}){
  const next=theme==='dark'?'light':'dark'
  return <button type="button" className="theme-toggle" aria-label={`Switch to ${next} mode`} title={`Switch to ${next} mode`} onClick={onToggle}>{theme==='dark'?<Sun size={17}/>:<Moon size={17}/>}<span>{theme==='dark'?'Light':'Dark'}</span></button>
}

function CursorAura(){
  const auraRef=useRef(null)
  useEffect(()=>{
    if(!window.matchMedia('(pointer:fine)').matches||window.matchMedia('(prefers-reduced-motion: reduce)').matches)return
    const aura=auraRef.current
    let frame=0
    const move=event=>{
      cancelAnimationFrame(frame)
      frame=requestAnimationFrame(()=>{
        aura.style.setProperty('--cursor-x',`${event.clientX}px`)
        aura.style.setProperty('--cursor-y',`${event.clientY}px`)
        aura.classList.add('cursor-visible')
      })
    }
    const down=()=>aura.classList.add('cursor-pressed')
    const up=()=>aura.classList.remove('cursor-pressed')
    const over=event=>aura.classList.toggle('cursor-interactive',event.target instanceof Element&&Boolean(event.target.closest('button,a,input,select,[role="button"]')))
    const leave=()=>aura.classList.remove('cursor-visible')
    window.addEventListener('pointermove',move,{passive:true})
    window.addEventListener('pointerdown',down)
    window.addEventListener('pointerup',up)
    document.addEventListener('pointerover',over)
    document.documentElement.addEventListener('pointerleave',leave)
    return ()=>{
      cancelAnimationFrame(frame)
      window.removeEventListener('pointermove',move)
      window.removeEventListener('pointerdown',down)
      window.removeEventListener('pointerup',up)
      document.removeEventListener('pointerover',over)
      document.documentElement.removeEventListener('pointerleave',leave)
    }
  },[])
  return <span ref={auraRef} className="cursor-aura" aria-hidden="true"/>
}

function Insight({ label, text }) { return <div className="insight-block"><small>{label}</small><div className="prose compact">{text || 'No items identified.'}</div></div> }
function Empty({ icon, title, text }) { return <div className="empty-state"><span>{icon}</span><b>{title}</b><p>{text}</p></div> }
function safeName(value='video') { return value.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '').slice(0,70) || 'video' }
function downloadText(text, filename) { const link = document.createElement('a'); link.href = URL.createObjectURL(new Blob([text], {type:'text/plain'})); link.download = filename; link.click(); URL.revokeObjectURL(link.href) }

export default App
