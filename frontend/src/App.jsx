import React, { useEffect, useMemo, useRef, useState } from 'react'
import { PromptForm } from './components/PromptForm.jsx'
import { Preview } from './components/Preview.jsx'
import { Toolbar } from './components/Toolbar.jsx'
import { StatusBar } from './components/StatusBar.jsx'
import { createJob, stopJob, streamUrl, BACKEND_URL } from './lib/api.js'
import { downloadHtml } from './lib/download.js'
import { useLocalStorage } from './hooks/useLocalStorage.js'
import { useEventSource } from './hooks/useEventSource.js'

export default function App() {
  const [prompt, setPrompt] = useLocalStorage('contract:prompt', '')
  const [html, setHtml] = useLocalStorage('contract:html', '')
  const [jobId, setJobId] = useState(null)
  const [isGenerating, setIsGenerating] = useState(false)
  const [error, setError] = useState('')
  const [startedAt, setStartedAt] = useState(null)
  const [finishedAt, setFinishedAt] = useState(null)

  const scrollerRef = useRef(null)
  const es = useEventSource()

  // Auto-scroll preview while generating
  useEffect(() => {
    if (isGenerating && scrollerRef.current) {
      scrollerRef.current.scrollTop = scrollerRef.current.scrollHeight
    }
  }, [html, isGenerating])

  const elapsed = useMemo(() => {
    if (!startedAt) return 0
    const end = finishedAt || Date.now()
    return Math.max(0, Math.round((end - startedAt) / 1000))
  }, [startedAt, finishedAt])

  const wordCount = useMemo(() => {
    const text = html.replace(/<[^>]+>/g, ' ')
    return text.trim() ? text.trim().split(/\s+/).length : 0
  }, [html])

  async function handleGenerate() {
    if (!prompt.trim()) {
      setError('Please describe the business context first.')
      return
    }
    setError('')
    setHtml('')
    setFinishedAt(null)
    setIsGenerating(true)
    setStartedAt(Date.now())

    try {
      const { jobId } = await createJob(prompt)
      setJobId(jobId)
      es.start(streamUrl(jobId), {
        chunk: (data) => setHtml((prev) => prev + data),
        error: (msg) => setError((prev) => prev || msg || 'Streaming error'),
        done: () => {
          setIsGenerating(false)
          setFinishedAt(Date.now())
        },
        onerror: () => {
          setError((prev) => prev || 'Connection lost while streaming.')
          setIsGenerating(false)
          setFinishedAt(Date.now())
        }
      })
    } catch (e) {
      setError(e.message || String(e))
      setIsGenerating(false)
      setFinishedAt(Date.now())
      es.stop()
    }
  }

  async function handleStop() {
    if (!jobId) return
    try { await stopJob(jobId) } catch {}
    es.stop()
    setIsGenerating(false)
    setFinishedAt(Date.now())
  }

  function handleDownload() {
    if (!html) return
    const timestamp = new Date().toISOString().slice(0,19)
    downloadHtml(
      `<!doctype html>\n<html><head><meta charset=\"utf-8\"><title>Contract</title>` +
      `<style>${EMBEDDED_CSS}</style></head><body>${html}</body></html>`,
      `contract-${timestamp}.html`
    )
  }

  return (
    <div style={styles.page}>
      <header style={styles.header}>
        <h1 style={{ margin: 0 }}>AI Contract Generator</h1>
        <div style={{ opacity: 0.7, fontSize: 14 }}>
          {isGenerating ? 'Streaming…' : finishedAt ? 'Ready' : 'Idle'} · {elapsed}s · {wordCount} words
        </div>
      </header>

      <section style={styles.panel}>
        <PromptForm
          prompt={prompt}
          setPrompt={setPrompt}
          onGenerate={handleGenerate}
          onStop={handleStop}
          isGenerating={isGenerating}
        />
        <StatusBar error={error} />
      </section>

      <section style={styles.previewWrap}>
        <div style={styles.previewHeader}><span>Live Preview (HTML)</span></div>
        <Preview
          html={html}
          placeholderHTML={placeholderHTML}
          ref={scrollerRef}
        />
      </section>

      <Toolbar
        backendUrl={BACKEND_URL}
        hasContent={!!html}
        onDownload={handleDownload}
      />
    </div>
  )
}

const styles = {
  page: {
    maxWidth: 1100,
    margin: '24px auto',
    padding: '0 16px 48px',
    fontFamily: `ui-sans-serif, -apple-system, Segoe UI, Roboto, Helvetica, Arial`,
    color: '#0f172a',
  },
  header: { display: 'flex', alignItems: 'baseline', gap: 12, justifyContent: 'space-between', marginBottom: 16 },
  panel: { background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 12, padding: 16 },
  previewWrap: { marginTop: 16, border: '1px solid #e2e8f0', borderRadius: 12, overflow: 'hidden' },
  previewHeader: { padding: 10, background: '#f1f5f9', borderBottom: '1px solid #e2e8f0', fontWeight: 600 },
}

const placeholderHTML = `
  <h2 style="margin:0 0 8px 0;">Your contract will appear here…</h2>
  <p style="margin:0 0 24px 0;">Click <strong>Generate</strong> to start streaming.</p>
  <h3>Formatting expectations</h3>
  <ol>
    <li>Section numbering (1., 1.1, 1.2, …)</li>
    <li>Consistent headings (H1–H3)</li>
    <li>Readable paragraphs and lists</li>
  </ol>
`

const EMBEDDED_CSS = `
  body { font-family: ui-serif, Georgia, Cambria, 'Times New Roman', Times, serif; color: #111827; }
  h1,h2,h3 { color:#0f172a; }
  h1 { font-size: 28px; margin: 0 0 8px; }
  h2 { font-size: 22px; margin: 24px 0 8px; }
  h3 { font-size: 18px; margin: 20px 0 8px; }
  p { margin: 8px 0; }
  ol, ul { padding-left: 22px; }
  a { color: #0ea5e9; }
`
