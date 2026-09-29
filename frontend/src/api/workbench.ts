import { validateContract } from '../contracts/validate.ts'
import type { Task } from '../workbench/model.ts'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}
const messages: Record<string, string> = {
  FORBIDDEN: '当前账号没有账号管理权限。',
  ACCOUNT_CONFLICT: '账号名称已存在，请使用其他名称。',
  LAST_ADMIN_REQUIRED: '必须保留至少一个启用的管理员账号。',
  PROVIDER_DISABLED: '背景生成已被管理员禁用，请联系管理员或等待启用。',
  UNSUPPORTED_CAPABILITY:
    '供应商能力不支持当前参数（模型或比例），请检查配置。',
  UPLOAD_CONTENT_REJECTED:
    '图片内容或尺寸不符合要求，或包含未支持的附加元数据。请使用有效 PNG/JPEG。',
  CUTOUT_REVIEW_REQUIRED:
    '商品抠图尚未确认。请先生成抠图候选并确认边缘后再提交。',
  CUTOUT_SERVICE_UNAVAILABLE:
    '抠图服务未配置或暂不可用，请稍后重试或联系管理员。',
  CUTOUT_NO_FOREGROUND:
    '没有找到白底之外的商品主体。请确认是白底图，或调小白底容差后重试。',
  INVALID_ASSET: '图片内容或尺寸不符合上传要求，请选择有效的 PNG/JPEG。',
  INVALID_LAYOUT: '输出预设或模板不可用，请刷新配置。',
  TASK_CONFLICT: '任务状态已变化或不可重试，请刷新任务。',
  INVALID_CONTRACT: '请求内容不符合接口要求，请检查输入。',
}
export async function request<T>(
  path: string,
  token: string,
  init: RequestInit = {},
): Promise<T> {
  let response: Response
  try {
    response = await fetch(
      (/^\/v[23]\//.test(path) ? '/api' : '/api/v1') + path,
      {
        ...init,
        cache: 'no-store',
        credentials: 'omit',
        headers: {
          ...(token ? { Authorization: 'Bearer ' + token } : {}),
          ...init.headers,
        },
        signal: init.signal ?? AbortSignal.timeout(15000),
      },
    )
  } catch {
    throw new ApiError(
      0,
      '连接中断或超时。提交结果可能尚未返回，请使用原请求重发。',
    )
  }
  if (!response.ok) {
    const value = await response.json().catch(() => ({}))
    const code = value.code ?? value.error?.code
    const message =
      response.status === 401
        ? '账号或密码不正确，或会话已过期，请重新登录。'
        : response.status === 404
          ? '资源不存在或当前账号无权访问。'
          : response.status === 413
            ? '图片超过当前环境的文件或像素预算。'
            : response.status === 415
              ? '只支持内容匹配的 PNG/JPEG 图片。'
              : response.status === 429
                ? '请求过于频繁，请稍后重试。'
                : (messages[code] ?? '服务暂时不可用，请稍后重试。')
    throw new ApiError(response.status, message)
  }
  if (response.status === 204) return undefined as T
  if (!response.headers.get('content-type')?.includes('application/json'))
    return (await response.blob()) as T
  return (await response.json()) as T
}
export function json(body: unknown): RequestInit {
  return {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }
}
export function checkedTask(value: Task): Task {
  if (validateContract('task-response', value).length)
    throw new ApiError(0, '任务响应格式异常，请刷新查询，避免重复创建任务。')
  return value
}
