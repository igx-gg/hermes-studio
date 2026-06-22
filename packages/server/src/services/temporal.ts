import { Client, Connection } from '@temporalio/client'

export type TemporalRuntimeConfig = {
  address: string
  namespace: string
  taskQueue: string
  configured: boolean
}

export type TemporalStatus = TemporalRuntimeConfig & {
  reachable: boolean
  namespaceState?: string
  error?: string
}

const DEFAULT_NAMESPACE = 'default'
const DEFAULT_TASK_QUEUE = 'hermes-default'
const DEFAULT_TIMEOUT_MS = 5_000

function normalizeEnvValue(value: string | undefined): string {
  return String(value || '').trim()
}

function sanitizeError(error: unknown): string {
  if (error instanceof Error) return error.message
  return String(error || 'Unknown Temporal connection error')
}

function withTimeout<T>(promise: Promise<T>, timeoutMs: number, message: string): Promise<T> {
  let timeout: NodeJS.Timeout | undefined
  const timeoutPromise = new Promise<never>((_, reject) => {
    timeout = setTimeout(() => reject(new Error(message)), timeoutMs)
  })

  return Promise.race([promise, timeoutPromise]).finally(() => {
    if (timeout) clearTimeout(timeout)
  })
}

export function getTemporalConfig(env: NodeJS.ProcessEnv = process.env): TemporalRuntimeConfig {
  const address = normalizeEnvValue(env.TEMPORAL_ADDRESS || env.TEMPORAL_SERVER_ADDRESS)
  return {
    address,
    namespace: normalizeEnvValue(env.TEMPORAL_NAMESPACE) || DEFAULT_NAMESPACE,
    taskQueue: normalizeEnvValue(env.TEMPORAL_TASK_QUEUE) || DEFAULT_TASK_QUEUE,
    configured: Boolean(address),
  }
}

export async function checkTemporalStatus(timeoutMs = DEFAULT_TIMEOUT_MS): Promise<TemporalStatus> {
  const config = getTemporalConfig()
  if (!config.configured) {
    return {
      ...config,
      reachable: false,
      error: 'TEMPORAL_ADDRESS is not configured',
    }
  }

  let connection: Connection | undefined

  try {
    connection = await withTimeout(
      Connection.connect({ address: config.address }),
      timeoutMs,
      `Temporal connection timed out after ${timeoutMs}ms`,
    )

    const client = new Client({
      connection,
      namespace: config.namespace,
    })

    const namespace = await withTimeout(
      client.workflowService.describeNamespace({ namespace: config.namespace }),
      timeoutMs,
      `Temporal namespace check timed out after ${timeoutMs}ms`,
    )

    return {
      ...config,
      reachable: true,
      namespaceState: String(namespace.namespaceInfo?.state || ''),
    }
  } catch (error) {
    return {
      ...config,
      reachable: false,
      error: sanitizeError(error),
    }
  } finally {
    await connection?.close()
  }
}
