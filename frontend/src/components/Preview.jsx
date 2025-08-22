import React, { forwardRef } from 'react'
// Render streamed HTML. Consider sanitizing with DOMPurify in production.
export const Preview = forwardRef(function Preview({ html, placeholderHTML }, ref) {
  return (
    <div
      ref={ref}
      style={{ height: 520, overflow: 'auto', background: 'white', padding: 24, lineHeight: 1.6 }}
    >
      <div dangerouslySetInnerHTML={{ __html: html || placeholderHTML }} />
    </div>
  )
})
