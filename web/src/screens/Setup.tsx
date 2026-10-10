import { useMutation, useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useState } from 'react'
import { api } from '../api/client'
import { q, queryClient } from '../api/queries'
import { ErrorNotice, Loading, Notice } from '../ui/Notice'
import { Card, PageHead } from '../ui/Page'

const KEY_RE = /^[0-9A-Fa-f]{32}$/
const ID_RE = /^7656\d{13}$/

/**
 * `setup`: Steam API key + SteamID64. The key is write-only — the server
 * never returns it, so the field always starts empty and only says whether
 * one is stored.
 */
export function Setup() {
  const { data, error } = useQuery(q.setup)
  const [key, setKey] = useState('')
  const [steamId, setSteamId] = useState<string | null>(null)
  const [touched, setTouched] = useState(false)
  const id = steamId ?? data?.steam_id ?? ''
  const save = useMutation({
    mutationFn: () => api.saveSetup({ steam_api_key: key.trim(), steam_id: id.trim() }),
    onSuccess: (s) => {
      queryClient.setQueryData(q.setup.queryKey, s)
      setKey('')
      void queryClient.invalidateQueries()
    },
  })
  const keyErr = KEY_RE.test(key.trim()) ? null : 'The key is 32 hexadecimal characters.'
  const idErr = ID_RE.test(id.trim()) ? null : 'A SteamID64 is 17 digits and starts with 7656.'

  return (
    <>
      <PageHead title="Setup" sub="Connect the enforcer to your Steam account. Both values are checked live against Steam." />
      {error && <ErrorNotice error={error} />}
      {!data && !error && <Loading what="setup" />}
      {data && !data.configured && (
        <Notice tone="warning" title="Not configured yet">Every other screen needs these two values first.</Notice>
      )}
      {save.isSuccess && (
        <Notice tone="success" title="Saved">
          Steam accepted the key. <Link to="/">Go to the dashboard</Link>.
        </Notice>
      )}
      <Card className="narrow">
        <form
          className="stack"
          noValidate
          onSubmit={(e) => {
            e.preventDefault()
            setTouched(true)
            if (!keyErr && !idErr) save.mutate()
          }}
        >
          <div className="form-field">
            <label htmlFor="setup-key" className="field-label">Steam Web API key</label>
            <input
              id="setup-key"
              className={`input mono${touched && keyErr ? ' input-bad' : ''}`}
              type="password"
              autoComplete="off"
              spellCheck={false}
              value={key}
              autoFocus
              placeholder={data?.has_api_key ? 'A key is stored — type a new one to replace it' : '32 hex characters'}
              aria-invalid={touched && keyErr !== null}
              aria-describedby="setup-key-help"
              onChange={(e) => setKey(e.target.value)}
            />
            <p id="setup-key-help" className={touched && keyErr ? 'field-help text-danger' : 'field-help'}>
              {touched && keyErr ? keyErr : <>Get one at <a href="https://steamcommunity.com/dev/apikey" target="_blank" rel="noreferrer">steamcommunity.com/dev/apikey</a>. It is never shown again.</>}
            </p>
          </div>
          <div className="form-field">
            <label htmlFor="setup-id" className="field-label">SteamID64</label>
            <input
              id="setup-id"
              className={`input mono input-num${touched && idErr ? ' input-bad' : ''}`}
              inputMode="numeric"
              value={id}
              aria-invalid={touched && idErr !== null}
              aria-describedby="setup-id-help"
              onChange={(e) => setSteamId(e.target.value)}
            />
            <p id="setup-id-help" className={touched && idErr ? 'field-help text-danger' : 'field-help'}>
              {touched && idErr ? idErr : 'Your profile URL or steamid.io shows it.'}
            </p>
          </div>
          {save.error && <ErrorNotice error={save.error} />}
          <div className="actions">
            <button type="submit" className="btn btn-primary" disabled={save.isPending}>
              {save.isPending ? 'Checking with Steam…' : 'Save and verify'}
            </button>
          </div>
        </form>
      </Card>
    </>
  )
}
