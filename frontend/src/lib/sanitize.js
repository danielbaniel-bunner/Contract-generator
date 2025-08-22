// Placeholder. For production, install DOMPurify and sanitize streamed HTML before rendering.
// import DOMPurify from 'dompurify'
export function sanitize(html) {
  // return DOMPurify.sanitize(html)
  return html // no-op for this assignment; rely on trusted backend
}
