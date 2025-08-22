export const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || 'http://localhost:8000'

export async function createJob(prompt) {
  const res = await fetch(`${BACKEND_URL}/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ prompt }),
  })
  if (!res.ok) throw new Error(`Generate failed: ${res.status}`)
  return res.json() // { jobId }
}

export function streamUrl(jobId) {
  return `${BACKEND_URL}/stream/${jobId}`
}

export async function stopJob(jobId) {
  await fetch(`${BACKEND_URL}/stop`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ jobId }),
  })
}
