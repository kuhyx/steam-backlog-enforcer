// Registers every element the shell uses, then wires page-wide behaviour.
import '../commands/commandButton'
import '../commands/palette'
import '../commands/runnerDialog'
import '../jobs/jobProgress'
import '../library/gameBrowser'
import '../shell/health'
import '../shell/jobIndicator'
import { boot } from '../shell/boot'

boot()
