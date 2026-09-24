import { Ajv2020 } from 'ajv/dist/2020.js'
import addFormats from 'ajv-formats'
import schema0 from '../../../contracts/common.schema.json' with { type: 'json' }
import schema1 from '../../../contracts/task-create.schema.json' with { type: 'json' }
import schema2 from '../../../contracts/idempotency-key.schema.json' with { type: 'json' }
import schema3 from '../../../contracts/task.schema.json' with { type: 'json' }
import schema4 from '../../../contracts/task-completed.schema.json' with { type: 'json' }
import schema5 from '../../../contracts/task-failed.schema.json' with { type: 'json' }
import schema6 from '../../../contracts/task-response.schema.json' with { type: 'json' }

const ajv = new Ajv2020({ strict: true, allErrors: true })
addFormats(ajv, { mode: 'full' })
for (const schema of [
  schema0,
  schema1,
  schema2,
  schema3,
  schema4,
  schema5,
  schema6,
])
  ajv.addSchema(schema)
const contracts: Record<string, string> = {
  'task-create':
    'https://schemas.product-image-workbench.invalid/v1/task-create.json',
  'idempotency-key':
    'https://schemas.product-image-workbench.invalid/v1/idempotency-key.json',
  'task-request':
    'https://schemas.product-image-workbench.invalid/v1/task-request.json',
  'task-completed':
    'https://schemas.product-image-workbench.invalid/v1/task-completed.json',
  'task-failed':
    'https://schemas.product-image-workbench.invalid/v1/task-failed.json',
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
