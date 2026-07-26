import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import './index.css'
import App from './App.tsx'
import { Toaster } from '@/components/ui/sonner'

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Individual hooks override this per docs §5.2/§6.2 caching rules;
      // this is just a sane global fallback.
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
      <Toaster position="top-right" richColors />
    </QueryClientProvider>
  </StrictMode>
)
