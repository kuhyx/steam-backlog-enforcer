// Fake job bodies, one per command. They pace themselves like the real CLI
// (HLTB lookups are slow, ProtonDB fast) so the progress UI has something to show.

import type { CommandName } from '../src/api/contract.ts'
import { resetToday } from './budget.ts'
import { GAMES, makeInstalled, makeWebGame } from './games.ts'
import type { JobCtx, Script } from './jobs.ts'
import { gameName, journal, library, world } from './world.ts'

const sample = (n: number) => GAMES.filter(([id]) => !world.finished.includes(id)).slice(0, n)

async function walk(ctx: JobCtx, label: string, items: string[], ms: number): Promise<void> {
  for (const [i, item] of items.entries()) {
    ctx.progress(i + 1, items.length, label, item, Math.round(((items.length - i - 1) * ms) / 1000))
    await ctx.sleep(ms)
  }
}

const scan: Script = async (ctx) => {
  ctx.progress(0, null, 'Fetching owned games from Steam')
  ctx.log('GET IPlayerService/GetOwnedGames → 512 apps')
  await ctx.sleep(2000)
  const games = sample(36).map(([, n]) => n)
  await walk(ctx, 'Fetching HLTB times', games, 450)
  ctx.log('HLTB: 33 matched, 3 without data (kept as -1)', 'warning')
  await walk(ctx, 'Reading ProtonDB tiers', games, 90)
  ctx.progress(1, 1, 'Assigning the shortest qualifying game')
  await ctx.sleep(600)
  ctx.log(`Assigned: ${gameName(world.currentAppId ?? 1145360)} (unchanged)`)
  return { summary: `Scanned 512 apps, 36 candidates; assignment unchanged (${gameName(world.currentAppId ?? 0)}).` }
}

const check: Script = async (ctx) => {
  const name = gameName(world.currentAppId ?? 0)
  ctx.progress(1, 2, 'Fetching achievements', name)
  await ctx.sleep(1200)
  ctx.progress(2, 2, 'Comparing with last snapshot', name)
  await ctx.sleep(600)
  ctx.log('41 of 49 achievements, no new ones since 2026-10-08')
  return { summary: `No new achievement in ${name} yet.` }
}

const done: Script = async (ctx) => {
  const name = gameName(world.currentAppId ?? 0)
  ctx.progress(1, 3, 'Checking for a new achievement', name)
  await ctx.sleep(1200)
  ctx.log(`New achievement found in ${name}: "Is There Anybody Out There?"`)
  const yes = await ctx.prompt('confirm', `Mark ${name} finished and assign the next game?`, { default: 'yes' })
  if (yes !== 'yes') return { summary: `Kept ${name} assigned.` }
  ctx.progress(2, 3, 'Refreshing HLTB times for candidates')
  await ctx.sleep(1500)
  const next = sample(3).find(([id]) => id !== world.currentAppId)!
  if (world.currentAppId !== null) world.finished.push(world.currentAppId)
  world.currentAppId = next[0]
  world.installed = makeInstalled(next[0])
  ctx.progress(3, 3, 'Assigning next game', next[1])
  await ctx.sleep(500)
  return { summary: `${name} done. Next up: ${next[1]}.` }
}

const pick: Script = async (ctx) => {
  ctx.progress(1, 2, 'Ranking candidates')
  await ctx.sleep(1500)
  const options = sample(6).map(([id, n]) => {
    const g = makeWebGame(id, n)
    return { value: String(id), label: n, detail: `${g.leisure_hours > 0 ? g.leisure_hours : '?'} h leisure · ProtonDB ${g.protondb_tier}` }
  })
  options.push({ value: 'own', label: 'Pick my own game…', detail: 'Any owned game you have not 100%-completed' })
  let chosen = 'own'
  while (chosen === 'own') {
    chosen = await ctx.prompt('choice', 'Pick your next game:', { options })
    if (chosen !== 'own') break
    const appIds = library().games.filter((g) => g.ineligible_reason === null).map((g) => g.app_id)
    // An empty answer goes back to the list, like the real job.
    chosen = (await ctx.prompt('game', 'Pick your next game', { app_ids: appIds })) || 'own'
  }
  ctx.progress(2, 2, 'Assigning', gameName(Number(chosen)))
  await ctx.sleep(700)
  world.currentAppId = Number(chosen)
  return { summary: `Assigned ${gameName(Number(chosen))}.` }
}

const install: Script = async (ctx) => {
  const name = gameName(world.currentAppId ?? 0)
  const dir = await ctx.prompt('text', 'Steam library folder to install into:', { default: '/mnt/games/SteamLibrary' })
  ctx.log(`steam://install/${world.currentAppId} → ${dir || '/mnt/games/SteamLibrary'}`)
  for (let i = 1; i <= 20; i += 1) {
    ctx.progress(i, 20, 'Downloading', `${name} — ${(i * 0.6).toFixed(1)} of 12.0 GB`, (20 - i) * 0.4)
    await ctx.sleep(400)
  }
  return { summary: `${name} installed.` }
}

const uninstall: Script = async (ctx) => {
  const victims = world.installed.filter((g) => !g.assigned && !g.protected)
  const typed = await ctx.prompt('phrase', '2 of these games have local saves that are not in Steam Cloud.', {
    phrase: 'delete unsynced saves',
  })
  if (typed.trim() !== 'delete unsynced saves') throw new Error('Phrase did not match; nothing was uninstalled.')
  await walk(ctx, 'Uninstalling', victims.map((g) => g.name), 700)
  world.installed = world.installed.filter((g) => g.assigned || g.protected)
  return { summary: `Uninstalled ${victims.length} games.` }
}

const simple = (label: string, summary: string, steps = 5): Script => async (ctx) => {
  await walk(ctx, label, Array.from({ length: steps }, (_, i) => `batch ${i + 1}`), 500)
  return { summary }
}

const unblock: Script = async (ctx) => {
  const minutes = Number(ctx.params.minutes)
  ctx.progress(1, 1, 'Asking the daemon to lift the store block')
  await ctx.sleep(900)
  world.storeBlockedUntil = Date.now() + minutes * 60_000
  journal(`store unblocked for ${minutes} min (web)`)
  return { summary: `Store unblocked for ${minutes} minutes.` }
}

const enforce: Script = async (ctx) => {
  if (ctx.params.mode === 'demo') {
    await walk(ctx, 'Demo enforcement (60 s budget)', ['arm', 'tick', 'tick', 'warn', 'cutoff'], 900)
    return { summary: 'Demo run finished: cutoff engaged after 60 s.' }
  }
  ctx.progress(1, 3, 'Flushing state')
  await ctx.sleep(700)
  ctx.progress(2, 3, 'Restarting daemon')
  world.daemon = 'restarting'
  journal('restart requested over ctl.sock (state flushed)')
  await ctx.sleep(2500)
  world.daemon = 'running'
  world.daemonStartedAt = Date.now()
  world.restartAvailableAt = Date.now() + 10 * 60_000
  journal('enforce loop started (tick 3s)')
  ctx.progress(3, 3, 'Waiting for first tick')
  await ctx.sleep(600)
  return { summary: 'Daemon restarted. Next restart possible in 10 minutes.' }
}

export const gamingReset: Script = async (ctx) => {
  ctx.progress(1, 1, 'Committing reset over ctl.sock')
  await ctx.sleep(800)
  resetToday()
  journal('gaming budget reset by user (logged to ledger)')
  return { summary: "Today's gaming counter reset to 0." }
}

export const restoreBackup = (id: string): Script => async (ctx) => {
  await walk(ctx, 'Restoring backup', ['state.json', 'snapshot.json', 'hltb_cache.json'], 600)
  return { summary: `Restored backup ${id}.` }
}

export const SCRIPTS: Partial<Record<CommandName, Script>> = {
  scan,
  check,
  done,
  pick,
  install,
  uninstall,
  unblock,
  'buy-dlc': unblock,
  enforce,
  hide: simple('Hiding non-assigned games', 'Hid 511 games; 1 visible.'),
  unhide: simple('Unhiding games', 'All 512 games visible again.'),
  'block-gaming': async (ctx) => {
    ctx.progress(1, 1, 'Installing total block')
    await ctx.sleep(1200)
    world.totalBlockUntil = Date.now() + Number(ctx.params.days) * 86_400_000
    world.lock = 'total'
    return { summary: `All gaming blocked for ${ctx.params.days} days.` }
  },
  'gaming-unblock': simple('Releasing bind mounts', 'Released 2 playtime bind mounts.', 2),
  'pick-manual': async (ctx) => {
    await ctx.sleep(800)
    world.manualPicks.push({ app_id: Number(ctx.params.app_id), picked_at: Date.now() })
    return { summary: `Locked in ${gameName(Number(ctx.params.app_id))} for 14 days.` }
  },
  'abandon-pick': async (ctx) => {
    await ctx.sleep(800)
    world.manualPicks = world.manualPicks.filter((p) => p.app_id !== Number(ctx.params.app_id))
    return { summary: `Abandoned ${gameName(Number(ctx.params.app_id))}.` }
  },
  'add-exception': async (ctx) => {
    await ctx.sleep(800)
    return { summary: `Exception for ${gameName(Number(ctx.params.app_id))} requested; usable in 24 h.` }
  },
  reset: async (ctx) => {
    ctx.progress(1, 2, 'Writing backup')
    await ctx.sleep(900)
    world.backups.unshift({ id: new Date().toISOString().replace(/\D/g, '').slice(0, 14), created_at: new Date().toISOString(), reason: 'before reset', size_bytes: 48_000 })
    ctx.progress(2, 2, 'Wiping state')
    await ctx.sleep(900)
    return { summary: 'State wiped; backup saved.' }
  },
}
