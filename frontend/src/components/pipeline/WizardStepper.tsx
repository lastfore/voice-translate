import { cn } from '@/lib/utils'
import type { StageName } from '@/types/pipeline'

interface WizardStepperProps {
  stages: StageName[]
  active: StageName
  onChange: (stage: StageName) => void
}

export function WizardStepper({ stages, active, onChange }: WizardStepperProps) {
  return (
    <div className="flex items-center gap-2" data-testid="wizard-stepper">
      {stages.map((stage, index) => (
        <button
          key={stage}
          type="button"
          onClick={() => onChange(stage)}
          data-testid={`wizard-step-${stage}`}
          className={cn(
            'rounded-md border px-3 py-1 text-sm transition-colors',
            active === stage
              ? 'border-primary bg-primary text-primary-foreground'
              : 'border-input hover:bg-accent'
          )}
        >
          {index + 1}. {stage}
        </button>
      ))}
    </div>
  )
}
