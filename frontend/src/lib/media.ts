/** Build a same-origin media URL for a repo-relative artifact path. */
export function mediaUrlFromPath(path: string | null | undefined): string | null {
  if (!path?.trim()) return null
  if (path.startsWith('/api/media')) return path
  return `/api/media?path=${encodeURIComponent(path.replace(/\\/g, '/'))}`
}

/** Force the browser to reload an audio preview after re-running a stage. */
export function withMediaCacheBuster(url: string, revision: number): string {
  if (revision <= 0) return url
  const sep = url.includes('?') ? '&' : '?'
  return `${url}${sep}_=${revision}`
}
