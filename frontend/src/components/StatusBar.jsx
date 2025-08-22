import React from 'react'

export function StatusBar({ error }) {
  if (!error) return null
  return (
    <div role="alert" style={{
      marginTop: 10,
      padding: 10,
      borderRadius: 8,
      background: '#fee2e2',
      color: '#991b1b',
      border: '1px solid #fecaca',
    }}>
      {error}
    </div>
  )
}
