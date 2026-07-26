import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'

import { projectDefaultsKey } from '@/hooks/useProjectDefaults'

interface ProjectContextValue {
  projectId: string | null
  setProjectId: (next: string | null) => void
}

const ProjectContext = createContext<ProjectContextValue | null>(null)

export function ProjectProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const [projectId, setProjectIdState] = useState<string | null>(null)
  const previousIdRef = useRef<string | null>(null)

  const setProjectId = useCallback(
    (next: string | null) => {
      const previous = previousIdRef.current
      if (previous && previous !== next) {
        // Migration doc §6.2 rule 4: drop the old project's cached defaults so
        // a stale reference never leaks into the newly-mounted forms — the
        // `key={projectId}` remount pattern only protects against *reset*
        // races, not against reading a cache entry that's still there.
        queryClient.removeQueries({ queryKey: projectDefaultsKey(previous) })
      }
      previousIdRef.current = next
      setProjectIdState(next)
    },
    [queryClient]
  )

  return <ProjectContext.Provider value={{ projectId, setProjectId }}>{children}</ProjectContext.Provider>
}

export function useProject(): ProjectContextValue {
  const ctx = useContext(ProjectContext)
  if (!ctx) {
    throw new Error('useProject must be used within a ProjectProvider')
  }
  return ctx
}
