import { LandingLogin } from '@/components/auth/landing-login'

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string }>
}) {
  const { next } = await searchParams
  return <LandingLogin returnTo={next} />
}
