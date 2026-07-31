import { AppSidebar } from '@/components/layout/AppSidebar'
import { ProjectHeader } from '@/components/projects/ProjectHeader'
import { BatchQueuePage } from '@/pages/BatchQueuePage'
import { ConvertPage } from '@/pages/ConvertPage'
import { DeharmonizePage } from '@/pages/DeharmonizePage'
import { MergePage } from '@/pages/MergePage'
import { SeparatePage } from '@/pages/SeparatePage'
import { SlicePage } from '@/pages/SlicePage'
import { WizardPage } from '@/pages/WizardPage'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ProjectProvider } from '@/context/ProjectContext'

function AppShell() {
  return (
    <div className="flex h-screen w-full overflow-hidden">
      <aside className="flex h-full w-72 shrink-0 flex-col border-r">
        <AppSidebar />
      </aside>
      <main className="flex min-h-0 flex-1 flex-col overflow-hidden">
        <div className="flex-1 overflow-y-auto p-6">
          <ProjectHeader />
          <Tabs defaultValue="separate" className="w-full">
            <TabsList>
              <TabsTrigger value="wizard" data-testid="tab-wizard">
                向导
              </TabsTrigger>
              <TabsTrigger value="separate" data-testid="tab-separate">
                分离
              </TabsTrigger>
              <TabsTrigger value="deharmonize" data-testid="tab-deharmonize">
                和声剥离
              </TabsTrigger>
              <TabsTrigger value="slice" data-testid="tab-slice">
                切片
              </TabsTrigger>
              <TabsTrigger value="convert" data-testid="tab-convert">
                转换
              </TabsTrigger>
              <TabsTrigger value="merge" data-testid="tab-merge">
                合并
              </TabsTrigger>
              <TabsTrigger value="batch" data-testid="tab-batch">
                批量队列
              </TabsTrigger>
            </TabsList>
            <TabsContent value="wizard" className="mt-4">
              <WizardPage />
            </TabsContent>
            <TabsContent value="separate" className="mt-4">
              <SeparatePage />
            </TabsContent>
            <TabsContent value="deharmonize" className="mt-4">
              <DeharmonizePage />
            </TabsContent>
            <TabsContent value="slice" className="mt-4">
              <SlicePage />
            </TabsContent>
            <TabsContent value="convert" className="mt-4">
              <ConvertPage />
            </TabsContent>
            <TabsContent value="merge" className="mt-4">
              <MergePage />
            </TabsContent>
            <TabsContent value="batch" className="mt-4">
              <BatchQueuePage />
            </TabsContent>
          </Tabs>
        </div>
      </main>
    </div>
  )
}

function App() {
  return (
    <ProjectProvider>
      <AppShell />
    </ProjectProvider>
  )
}

export default App
