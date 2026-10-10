import { Link } from '@tanstack/react-router'
import { PageHead } from '../ui/Page'

export function NotFound() {
  return (
    <>
      <PageHead title="Not found" sub="There is no screen at this address." />
      <Link to="/" className="btn btn-primary">Back to the dashboard</Link>
    </>
  )
}
