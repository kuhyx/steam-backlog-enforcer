// Backlog page elements (was screens/Backlog.tsx): the `stats` card and the
// interactive planner.

import { define } from '../../lib/dom'
import { GameTableElement } from './gameTable'
import { BacklogStatsElement } from './stats'

define('backlog-stats', BacklogStatsElement)
define('game-table', GameTableElement)
