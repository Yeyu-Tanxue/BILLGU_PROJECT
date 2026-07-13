export async function apiFetch(path: string, init?: RequestInit) {
  const normalizedPath = path.startsWith('/') ? path : `/${path}`
  const res = await fetch(`/bff${normalizedPath}`, {
    ...init,
    credentials: 'include',
  })
  if (res.status === 401 && init?.redirect !== 'manual') {
    if (typeof window !== 'undefined') {
      const returnTo = encodeURIComponent(window.location.pathname + window.location.search)
      window.location.href = `/auth/login?returnTo=${returnTo}`
    }
  }
  return res
}
