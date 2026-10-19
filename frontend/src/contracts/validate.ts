import { Ajv2020 } from 'ajv/dist/2020.js'
import addFormats from 'ajv-formats'
import common from '../../../contracts/common.schema.json' with { type: 'json' }
import idempotencyKey from '../../../contracts/idempotency-key.schema.json' with { type: 'json' }
import taskResponse from '../../../contracts/task-response.schema.json' with { type: 'json' }
import generationCreate from '../../../contracts/generation-v4-create.schema.json' with { type: 'json' }
import generationRetypeset from '../../../contracts/generation-v4-retypeset.schema.json' with { type: 'json' }
import presetCatalog from '../../../contracts/preset-catalog.schema.json' with { type: 'json' }
import userTemplate from '../../../contracts/user-template.schema.json' with { type: 'json' }
import canvasLayout from '../../../contracts/canvas-layout.schema.json' with { type: 'json' }

const ajv = new Ajv2020({ strict: true, allErrors: true })
addFormats(ajv, { mode: 'full' })
for (const schema of [
  common,
  idempotencyKey,
  taskResponse,
  generationCreate,
  generationRetypeset,
  presetCatalog,
  userTemplate,
  canvasLayout,
])
  ajv.addSchema(schema)
const contracts: Record<string, string> = {
  'preset-catalog':
    'https://schemas.product-image-workbench.invalid/v4/preset-catalog.json',
  'user-template':
    'https://schemas.product-image-workbench.invalid/v4/user-template.json',
  'canvas-layout':
    'https://schemas.product-image-workbench.invalid/v4/canvas-layout.json',
  'generation-v4-create':
    'https://schemas.product-image-workbench.invalid/v4/generation-create.json',
  'generation-v4-retypeset':
    'https://schemas.product-image-workbench.invalid/v4/generation-retypeset.json',
  'idempotency-key':
    'https://schemas.product-image-workbench.invalid/v1/idempotency-key.json',
  'task-response':
    'https://schemas.product-image-workbench.invalid/v1/task-response.json',
}

// Return only schema paths/keywords; never echo prompts, object keys or credentials.
export function validateContract(name: string, value: unknown): string[] {
  const id = contracts[name]
  if (!id) throw new Error('Unknown contract')
  const validate = ajv.getSchema(id)!
  return validate(value)
    ? []
    : (validate.errors ?? []).map(
        (error) => `${error.schemaPath}: ${error.keyword}`,
      )
}
