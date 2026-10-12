import catalog from '../../../contracts/model-parameters.json' with { type: 'json' }

export type Purpose = 'IMAGE' | 'TEXT'
/** One official model parameter the admin may fill in (ADR-20261012-AB). */
export type ParamSpec = {
  name: string
  label: string
  type: 'enum' | 'number' | 'integer'
  values?: { value: string; label: string }[]
  min?: number
  max?: number
  /** Shown as "官方默认：…"; a blank field is not sent, so this default applies. */
  official_default: string
  help?: string
}
export type ParamValue = string | number | boolean
type Kind = {
  label: string
  purposes: Purpose[]
  offered: boolean
  examples: Partial<Record<Purpose, string[]>>
}
type ParamSet = {
  id: string
  name: string
  kinds: string[]
  purpose: Purpose
  match: string
  parameters: ParamSpec[]
  resolutions?: Record<string, Record<string, string>>
  help?: string
}
const kinds = catalog.kinds as unknown as Record<string, Kind>
const sets = catalog.sets as unknown as ParamSet[]

/** The interface types an admin can add, in catalog order. */
export const offeredKinds = Object.entries(kinds)
  .filter(([, kind]) => kind.offered)
  .map(([id, kind]) => ({ id, label: kind.label }))
export const kindLabel = (kind: string) => kinds[kind]?.label ?? kind
export const kindPurposes = (kind: string): Purpose[] =>
  kinds[kind]?.purposes ?? []
export const modelExamples = (kind: string, purpose: Purpose) =>
  kinds[kind]?.examples[purpose] ?? []

/** The parameter set for a model under an interface type; same matching as the server. */
export function paramSet(
  kind: string,
  model: string,
  purpose: Purpose,
): ParamSet | undefined {
  if (!model.trim()) return undefined
  return sets.find(
    (item) =>
      item.kinds.includes(kind) &&
      item.purpose === purpose &&
      new RegExp(item.match).test(model),
  )
}
export const paramSpecs = (kind: string, model: string, purpose: Purpose) =>
  paramSet(kind, model, purpose)?.parameters ?? []

/** A filled-in field as it is stored: numbers as numbers, an emptied field as nothing. */
export function parseParam(
  spec: ParamSpec,
  raw: string,
): ParamValue | undefined | null {
  const text = raw.trim()
  if (!text) return undefined
  if (spec.type === 'enum')
    return spec.values?.some((item) => item.value === text) ? text : null
  const number = Number(text)
  if (!Number.isFinite(number)) return null
  if (spec.type === 'integer' && !Number.isInteger(number)) return null
  if (
    (spec.min !== undefined && number < spec.min) ||
    (spec.max !== undefined && number > spec.max)
  )
    return null
  return number
}

/** Short summary for the model table, e.g. "画质：高，随机种子：42". */
export function paramSummary(
  kind: string,
  model: string,
  purpose: Purpose,
  values: Record<string, ParamValue> | undefined,
): string {
  const specs = paramSpecs(kind, model, purpose)
  return Object.entries(values ?? {})
    .map(([key, value]) => {
      const spec = specs.find((item) => item.name === key)
      const label = spec?.values?.find((item) => item.value === value)?.label
      return `${spec?.label ?? key}：${label ?? value}`
    })
    .join('，')
}
