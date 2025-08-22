import React from 'react'

export function PromptForm({ prompt, setPrompt, onGenerate, onStop, isGenerating }) {
  return (
    <div>
      <label htmlFor="prompt" style={{ display: 'block', marginBottom: 8, fontWeight: 600 }}>
        Describe your business context
      </label>
      <textarea
        id="prompt"
        placeholder="e.g., Draft Terms of Service for a cloud cyber SaaS company based in New York"
        value={prompt}
        onChange={(e) => setPrompt(e.target.value)}
        rows={5}
        style={{
          width: '100%',
          resize: 'vertical',
          borderRadius: 10,
          border: '1px solid #cbd5e1',
          padding: 12,
          fontSize: 14,
          outline: 'none',
        }}
      />
      <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
        <button
          onClick={onGenerate}
          disabled={isGenerating}
          style={{
            appearance: 'none',
            border: '1px solid #0ea5e9',
            background: '#0ea5e9',
            padding: '10px 14px',
            borderRadius: 10,
            cursor: 'pointer',
            fontWeight: 600,
            color: 'white',
            opacity: isGenerating ? 0.8 : 1,
          }}
        >
          {isGenerating ? 'Generating…' : 'Generate'}
        </button>
        <button
          onClick={onStop}
          disabled={!isGenerating}
          style={{
            appearance: 'none',
            border: '1px solid #cbd5e1',
            background: 'white',
            padding: '10px 14px',
            borderRadius: 10,
            cursor: 'pointer',
            fontWeight: 600,
          }}
        >
          Stop
        </button>
      </div>
    </div>
  )
}
