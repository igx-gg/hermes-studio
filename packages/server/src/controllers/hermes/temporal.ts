import type { Context } from 'koa'
import { checkTemporalStatus } from '../../services/temporal'

export async function status(ctx: Context) {
  const timeout = Number(ctx.query.timeout_ms || 5000)
  const timeoutMs = Number.isFinite(timeout)
    ? Math.min(Math.max(timeout, 1000), 30000)
    : 5000

  const temporal = await checkTemporalStatus(timeoutMs)
  ctx.status = temporal.reachable ? 200 : 503
  ctx.body = { temporal }
}
