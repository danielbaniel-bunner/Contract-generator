import React from 'react'
import { downloadHtml } from '../lib/download.js'

export function Toolbar({ backendUrl, hasContent, onDownload }) {
  return (
    <footer style={{ marginTop: 16, display:'flex', alignItems:'center', justifyContent:'space-between' }}>
      <div style={{ opacity: 0.7 }}>
        Backend: <code>{backendUrl}</code>
      </div>
      <div>
        <button
          onClick={onDownload}
          disabled={!hasContent}
          style={{
            appearance: 'none',
            border: '1px solid #cbd5e1',
            background: 'white',
            padding: '8px 12px',
            borderRadius: 10,
            cursor: hasContent ? 'pointer' : 'not-allowed',
            fontWeight: 600,
          }}
        >
          Download HTML
        </button>
      </div>
    </footer>
  )
}
