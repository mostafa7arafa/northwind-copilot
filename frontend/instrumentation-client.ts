// Sentry browser-side init. Opt-in: without NEXT_PUBLIC_SENTRY_DSN (baked at
// build time) this never sends anything. No replay/tracing — errors only.
import * as Sentry from "@sentry/nextjs";

if (process.env.NEXT_PUBLIC_SENTRY_DSN) {
  Sentry.init({
    dsn: process.env.NEXT_PUBLIC_SENTRY_DSN,
    environment: process.env.NEXT_PUBLIC_SENTRY_ENVIRONMENT ?? "production",
    tracesSampleRate: 0,
    sendDefaultPii: false,
  });
}

export const onRouterTransitionStart = Sentry.captureRouterTransitionStart;
