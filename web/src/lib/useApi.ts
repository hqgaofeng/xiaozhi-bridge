/**
 * useApi — minimal data-fetching hook for the V2 #5 admin console.
 *
 * Each page needs the same three states: loading, error, data.
 * This keeps the boilerplate out of the page components so they
 * stay focused on rendering.
 *
 * The hook re-fetches on mount, exposes a manual `refresh()` to
 * allow buttons like "重试" / "刷新", and tears down properly
 * when the component unmounts (so a fast route-switch doesn't
 * set state on a dead component).
 *
 * For V2 #5 we keep it intentionally simple: no caching, no
 * SWR-style dedup. Each page calls this once on mount; if we
 * need shared caches later, swap to react-query.
 */

import { useCallback, useEffect, useState } from 'react'

import { APIError } from './api'

interface UseApiResult<T> {
  data: T | null
  error: string | null
  loading: boolean
  refresh: () => void
}

export function useApi<T>(fetcher: () => Promise<T>): UseApiResult<T> {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState<boolean>(true)
  // Bumping this counter forces a re-run even when fetcher identity
  // is stable across renders (which it is — api.ts methods close
  // over nothing that changes).
  const [tick, setTick] = useState(0)

  const refresh = useCallback(() => {
    setTick((t) => t + 1)
  }, [])

  useEffect(() => {
    let alive = true
    setLoading(true)
    setError(null)
    fetcher()
      .then((result) => {
        if (!alive) return
        setData(result)
        setError(null)
      })
      .catch((e: unknown) => {
        if (!alive) return
        if (e instanceof APIError) {
          setError(`HTTP ${e.status}: ${e.message || '(no body)'}`)
        } else if (e instanceof Error) {
          setError(e.message)
        } else {
          setError(String(e))
        }
        setData(null)
      })
      .finally(() => {
        if (!alive) return
        setLoading(false)
      })
    return () => {
      alive = false
    }
    // fetcher is intentionally excluded from deps; tick acts as the
    // re-run trigger and re-creating the effect on every render
    // would cancel+restart mid-flight.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tick])

  return { data, error, loading, refresh }
}
