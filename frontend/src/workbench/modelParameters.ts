import catalog from '../../../contracts/model-parameters.json' with { type: 'json' }

/** One adjustable model parameter (ADR-20261009-Q). */
export type ParamSpec = {
  label: string
  default: string
  values: { value: string; label: string }[]
}
type Family = {
  id: string
  name: string
  purpose: 'IMAGE' | 'TEXT'
  match: string
  parameters: Record<string, ParamSpec>
}

/** The parameters an administrator may set for a model id; same matching as the server. */
export function paramSpecs(
  model: string,
  purpose: 'IMAGE' | 'TEXT',
): Record<string, ParamSpec> {
  if (!model.trim()) return {}
  const family = (catalog.families as unknown as Family[]).find(
    (item) => item.purpose === purpose && new RegExp(item.match).test(model),
  )
  return family?.parameters ?? {}
}

/** Short summary for the model table, e.g. "画质档：高". */
export function paramSummary(
  model: string,
  purpose: 'IMAGE' | 'TEXT',
  values: Record<string, string> | undefined,
): string {
  const specs = paramSpecs(model, purpose)
  return Object.entries(values ?? {})
    .map(([key, value]) => {
      const spec = specs[key]
      const label = spec?.values.find((item) => item.value === value)?.label
      return spec ? `${spec.label}：${label ?? value}` : `${key}：${value}`
    })
    .join('，')
}
