export interface BusinessHealth {
  status: 'UP'
  service: 'business-service'
  api_version: 'v1'
}

export async function fetchBusinessHealth(
  url = '/api/v1/health',
): Promise<BusinessHealth> {
  const response = await fetch(url, { signal: AbortSignal.timeout(5000) })
  if (!response.ok) {
    throw new Error(`服务连接失败（HTTP ${response.status}）`)
  }
  const body: unknown = await response.json()
  if (
    !body ||
    typeof body !== 'object' ||
    !('status' in body) ||
    body.status !== 'UP' ||
    !('service' in body) ||
    body.service !== 'business-service' ||
    !('api_version' in body) ||
    body.api_version !== 'v1'
  ) {
    throw new Error('服务响应格式不符合 v1 契约')
  }
  return {
    status: body.status,
    service: body.service,
    api_version: body.api_version,
  }
}
