import { useRef } from 'react'

// Tiny SSE manager so components stay clean.
export function useEventSource() {
  const esRef = useRef(null)
  const finishedRef = useRef(false)

  function start(url, handlers = {}) {
    stop() // safety: close any previous stream

    finishedRef.current = false
    const es = new EventSource(url)
    esRef.current = es

    // Optional: let caller know we're connected
    if (handlers.open) es.addEventListener('open', () => handlers.open())

    // Contract generator streams "chunk" events with HTML snippets
    if (handlers.chunk) {
      es.addEventListener('chunk', (e) => {
        // Some servers may send multi-line data; join if needed
        handlers.chunk(e.data)
      })
    }

    // Our backend emits an explicit "done" event.
    // Close immediately so the browser won't auto-reconnect.
    es.addEventListener('done', () => {
      finishedRef.current = true
      try { es.close() } catch {}
      esRef.current = null
      if (handlers.done) handlers.done()
    })

    // If the server sends an "error" event (custom) as data
    if (handlers.error) {
      es.addEventListener('error', (e) => {
        // This listener handles *custom* 'error' events from the server
        // (not the native EventSource onerror below).
        // Some servers include a message in e.data; default to generic text.
        if (finishedRef.current) return
        handlers.error(e?.data || 'Streaming error')
      })
    }

    // Native EventSource network errors (disconnects, retries, etc.)
    es.onerror = () => {
      if (finishedRef.current) return // ignore after a clean 'done'
      if (handlers.onerror) handlers.onerror() // optional separate callback
    }
  }

  function stop() {
    finishedRef.current = true
    if (esRef.current) {
      try { esRef.current.close() } catch {}
      esRef.current = null
    }
  }

  return { start, stop }
}
