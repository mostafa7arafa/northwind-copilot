// Sentry init for the Next.js Node runtime (SSR/route handlers).
import * as Sentry from "@sentry/nextjs";

if (process.env.NEXT_PUBLIC_SENTRY_DSN) {
  Sentry.init({
    dsn: process.env.NEXT_PUBLIC_SENTRY_DSN,
    environment: process.env.NEXT_PUBLIC_SENTRY_ENVIRONMENT ?? "production",
    tracesSampleRate: 0,
    sendDefaultPii: false,
  });
}
