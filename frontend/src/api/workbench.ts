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
  PROVIDER_DISABLED: '默认模型未启用，请选择其他模型或联系管理员。',
  UNSUPPORTED_CAPABILITY:
    '供应商能力不支持当前参数（模型或比例），请检查配置。',
  UPLOAD_CONTENT_REJECTED: '图片文件不完整或已损坏，请重新导出后上传。',
  INVALID_ASSET: '图片内容或尺寸不符合上传要求，请选择有效的 PNG/JPEG。',
  INVALID_LAYOUT:
    '尺寸、比例、数量或文字区域不符合要求（卖点图数量须等于所选风格数）。',
  TEXT_OVERFLOW: '文字放不下：请缩短文字、减小字号或放大文字区域。',
  PROVIDER_UNAVAILABLE: '生成服务暂不可用，请稍后重试或联系管理员。',
  TASK_CONFLICT: '任务状态已变化或不可重试，请刷新任务。',
  ASSET_IN_USE: '这张原图正在生成中使用，完成后再删除。',
  ASSET_DELETED: '原图已删除，不能再用于生成或重试。',
  INVALID_CONTRACT: '请求内容不符合接口要求，请检查输入。',
  MODEL_UNAVAILABLE: '所选模型已停用或不存在，请重新选择模型。',
  DEFAULT_MODEL: '默认模型不能停用或删除，请先把其他模型设为默认。',
  INTERFACE_IN_USE: '这个接口下还有模型，请先删除接口下的模型。',
  MODEL_QUALITY_UNSUPPORTED:
    '所选模型没有“高清”画质，请把画质改回标准或换一个模型。',
  MODEL_SIZE_UNSUPPORTED:
    '所选模型不能按 2K 出图，请把尺寸改回标准或换一个支持 2K 的模型。',
  SELF_DELETE: '不能删除当前登录的账号。',
  ACCOUNT_BUSY: '该账号还有生成中的任务，请稍后再删除。',
}
export async function request<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  let response: Response
  try {
    response = await fetch((/^\/v4\//.test(path) ? '/api' : '/api/v1') + path, {
      ...init,
      cache: 'no-store',
      // The session is an HttpOnly same-origin cookie set by Java at login;
      // scripts never see or store the token.
      credentials: 'same-origin',
      signal: init.signal ?? AbortSignal.timeout(15000),
    })
  } catch {
    throw new ApiError(
      0,
      '连接中断或超时。提交结果可能尚未返回，请用原请求重发，不会重复创建。',
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
            ? '图片超过服务器的安全上限（默认 50MB、1 亿像素），请压缩后再上传。'
            : response.status === 415
              ? '无法识别的图片格式。HEIC、TIFF 等格式请先另存为 JPG 或 PNG 再上传。'
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
