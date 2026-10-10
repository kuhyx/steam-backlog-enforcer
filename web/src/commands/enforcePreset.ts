import type { CommandSpec } from '../api/contract'

/**
 * `enforce` is two operations behind one catalog spec: `demo: 1` is a 60 s
 * demo that runs as a desktop-user job and loops until cancelled, `demo: 0`
 * is the daemon restart over ctl.sock (the server's `is_privileged`). The
 * System buttons preset one of them, so the dialog shows that operation's
 * own flags and keeps the mode out of the form — a restart dialog must not
 * turn into a demo, nor claim it can be cancelled.
 *
 * Returns the spec to render and the params to send whatever the form holds.
 */
export function enforcePreset(
  spec: CommandSpec,
  preset: Record<string, number | string> | undefined,
): { spec: CommandSpec; fixed: Record<string, number | string> } {
  if (spec.name !== 'enforce' || preset?.demo === undefined) return { spec, fixed: {} }
  const demo = Number(preset.demo) === 1
  return {
    spec: {
      ...spec,
      description: demo
        ? 'Run the enforcer with a 60-second demo budget and its own state file. It keeps running until you cancel it.'
        : 'Restart the enforcer daemon. State is flushed first and systemd brings it straight back; once per 10 minutes.',
      params: spec.params.filter((p) => p.name !== 'demo'),
      privileged: !demo,
      cancellable: demo,
    },
    fixed: { demo: demo ? 1 : 0 },
  }
}
