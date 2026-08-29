import { fmtDuration } from '../format'
import type { BudgetRules } from '../types'

interface Props {
  rules: BudgetRules
}

function onOff(value: boolean): string {
  return value ? 'on' : 'off'
}

export function BudgetRulesCard({ rules }: Props) {
  return (
    <section className="budget-rules">
      <h2>Rules in effect</h2>
      <dl className="budget-rules-list">
        <dt>Daily budget</dt>
        <dd>{fmtDuration(rules.budget_seconds)}</dd>
        <dt>Enforcement</dt>
        <dd>{onOff(rules.enforcement)}</dd>
        <dt>Engagement gate</dt>
        <dd>
          {onOff(rules.engagement_gate)} · idle grace {fmtDuration(rules.idle_grace_seconds)}
          {rules.require_game_focus ? ' · game must be focused' : ''}
        </dd>
        <dt>Counts launchers</dt>
        <dd>{rules.counts_launchers ? 'yes' : 'no'}</dd>
        <dt>Warnings at</dt>
        <dd>{rules.warn_at.map((s) => fmtDuration(s)).join(', ')} remaining</dd>
        {rules.demo && (
          <>
            <dt>Mode</dt>
            <dd>demo (short budget, separate state)</dd>
          </>
        )}
        {rules.masked_launchers.length > 0 && (
          <>
            <dt>Masked now</dt>
            <dd>{rules.masked_launchers.join(', ')}</dd>
          </>
        )}
      </dl>
    </section>
  )
}
