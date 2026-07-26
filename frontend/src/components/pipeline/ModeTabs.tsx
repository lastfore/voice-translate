import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'

export interface ModeTabsOption<T extends string> {
  value: T
  label: string
}

export interface ModeTabsProps<T extends string> {
  value: T
  onChange: (value: T) => void
  options: ModeTabsOption<T>[]
}

/**
 * Nested sub-tab mode selector — migrated from webui/components/mode_panel.py.
 * Unlike the Gradio version there's no index<->mode double-bookkeeping
 * (`gr.State` + `Tabs.select`): the mode string is the single source of
 * truth, and `Tabs` is fully controlled via `value`/`onValueChange`
 * (migration doc §5.8).
 */
export function ModeTabs<T extends string>({ value, onChange, options }: ModeTabsProps<T>) {
  return (
    <Tabs value={value} onValueChange={(v) => onChange(v as T)}>
      <TabsList>
        {options.map((option) => (
          <TabsTrigger key={option.value} value={option.value} data-testid={`mode-tab-${option.value}`}>
            {option.label}
          </TabsTrigger>
        ))}
      </TabsList>
    </Tabs>
  )
}
