import type { ReactNode } from 'react'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { ChevronDownIcon } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Form, FormControl, FormDescription, FormField, FormItem, FormLabel } from '@/components/ui/form'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { cn } from '@/lib/utils'
import type { StageParamSchema, StageParamValues } from '@/types/pipeline'

export interface StageParamFormProps {
  /** Param schema entries to render — caller pre-filters (e.g. vad_only for the active slice mode). */
  params: StageParamSchema[]
  /** Saved/resolved values to seed the form with on mount. Only read once (react-hook-form `defaultValues` semantics) — use `key={projectId}` on the parent to force a remount instead of calling `form.reset()` (migration doc §6.2). */
  defaultValues: StageParamValues
  onSubmit: (values: StageParamValues) => void
  submitLabel?: string
  isSubmitting?: boolean
  advancedLabel?: string
  defaultAdvancedOpen?: boolean
  extraFooter?: ReactNode
}

function coerceForSubmit(param: StageParamSchema, raw: unknown): unknown {
  if (param.param_type === 'bool') return !!raw
  if (param.param_type === 'int') return raw === '' || raw === undefined ? 0 : Math.trunc(Number(raw))
  if (param.param_type === 'float') return raw === '' || raw === undefined ? 0 : Number(raw)
  return raw
}

/**
 * Schema-driven stage parameter form — migrated from webui/components/stage_params.py.
 *
 * Critical fix vs. the Gradio version (migration doc §5.2/§9 "已知 Gradio 缺陷"):
 * bool params are rendered *outside* the Collapsible/advanced section so a
 * collapsed panel can never drop a checkbox value on submit
 * (`partition_bool_params()` server-side, mirrored here client-side).
 */
export function StageParamForm({
  params,
  defaultValues,
  onSubmit,
  submitLabel = '运行',
  isSubmitting = false,
  advancedLabel = '高级参数',
  defaultAdvancedOpen = false,
  extraFooter,
}: StageParamFormProps) {
  const [advancedOpen, setAdvancedOpen] = useState(defaultAdvancedOpen)

  const seeded: StageParamValues = {}
  for (const p of params) {
    seeded[p.key] = defaultValues[p.key] ?? p.default
  }

  const form = useForm<StageParamValues>({ defaultValues: seeded })

  const boolParams = params.filter((p) => p.param_type === 'bool')
  const otherParams = params.filter((p) => p.param_type !== 'bool')

  const handleSubmit = form.handleSubmit((values) => {
    const coerced: StageParamValues = {}
    for (const p of params) {
      coerced[p.key] = coerceForSubmit(p, values[p.key])
    }
    onSubmit(coerced)
  })

  return (
    <Form {...form}>
      <form onSubmit={handleSubmit} className="space-y-4" data-testid="stage-param-form">
        {boolParams.length > 0 && (
          <div className="space-y-3" data-testid="bool-params-outside-collapsible">
            {boolParams.map((param) => (
              <FormField
                key={param.key}
                control={form.control}
                name={param.key}
                render={({ field }) => (
                  <FormItem className="flex flex-row items-start gap-2 space-y-0">
                    <FormControl>
                      <Checkbox
                        checked={!!field.value}
                        onCheckedChange={field.onChange}
                        data-testid={`param-${param.key}`}
                      />
                    </FormControl>
                    <div className="grid gap-1 leading-none">
                      <FormLabel className="font-normal">{param.label}</FormLabel>
                      {param.description && <FormDescription>{param.description}</FormDescription>}
                    </div>
                  </FormItem>
                )}
              />
            ))}
          </div>
        )}

        {otherParams.length > 0 && (
          <Collapsible open={advancedOpen} onOpenChange={setAdvancedOpen}>
            <CollapsibleTrigger asChild>
              <Button type="button" variant="outline" size="sm" className="gap-1" data-testid="advanced-params-trigger">
                {advancedLabel}
                <ChevronDownIcon className={cn('size-4 transition-transform', advancedOpen && 'rotate-180')} />
              </Button>
            </CollapsibleTrigger>
            <CollapsibleContent className="space-y-4 pt-4" data-testid="advanced-params-content">
              {otherParams.map((param) => (
                <FormField
                  key={param.key}
                  control={form.control}
                  name={param.key}
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>{param.label}</FormLabel>
                      <FormControl>
                        {param.param_type === 'choice' ? (
                          <Select value={String(field.value ?? '')} onValueChange={field.onChange}>
                            <SelectTrigger className="w-full" data-testid={`param-${param.key}`}>
                              <SelectValue placeholder={param.label} />
                            </SelectTrigger>
                            <SelectContent>
                              {(param.choices ?? []).map((choice) => (
                                <SelectItem key={choice} value={choice}>
                                  {choice}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        ) : param.param_type === 'int' || param.param_type === 'float' ? (
                          <Input
                            type="number"
                            step={param.step ?? (param.param_type === 'int' ? 1 : 0.01)}
                            min={param.minimum ?? undefined}
                            max={param.maximum ?? undefined}
                            data-testid={`param-${param.key}`}
                            {...field}
                            value={field.value as number | string}
                            onChange={(e) => field.onChange(e.target.value)}
                          />
                        ) : (
                          <Input data-testid={`param-${param.key}`} {...field} value={field.value as string} />
                        )}
                      </FormControl>
                      {param.description && <FormDescription>{param.description}</FormDescription>}
                    </FormItem>
                  )}
                />
              ))}
            </CollapsibleContent>
          </Collapsible>
        )}

        <div className="flex items-center gap-3">
          <Button type="submit" disabled={isSubmitting} data-testid="stage-run-submit">
            {isSubmitting ? '运行中…' : submitLabel}
          </Button>
          {extraFooter}
        </div>
      </form>
    </Form>
  )
}
