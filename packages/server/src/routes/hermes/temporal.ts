import Router from '@koa/router'
import * as ctrl from '../../controllers/hermes/temporal'

export const temporalRoutes = new Router()

temporalRoutes.get('/api/hermes/temporal/status', ctrl.status)
