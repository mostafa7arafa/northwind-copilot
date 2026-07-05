import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// Auth gate for the hosted product. Only active when the build is configured
// for hosted mode; in the POC build there is no auth and this is a no-op.
//
// A missing session cookie on a protected page redirects to /login. This is a
// coarse presence check for UX (fast redirects) — every API route still
// enforces real auth server-side, so a forged cookie gains nothing.
const HOSTED = process.env.NEXT_PUBLIC_HOSTED_MODE === "true";
const SESSION_COOKIE = "nw_session";
const PUBLIC_PATHS = ["/login", "/signup"];

export function middleware(req: NextRequest) {
  if (!HOSTED) return NextResponse.next();

  const { pathname } = req.nextUrl;
  const isPublic = PUBLIC_PATHS.some((p) => pathname.startsWith(p));
  const hasSession = req.cookies.has(SESSION_COOKIE);

  if (!hasSession && !isPublic) {
    const url = req.nextUrl.clone();
    url.pathname = "/login";
    return NextResponse.redirect(url);
  }
  if (hasSession && isPublic) {
    const url = req.nextUrl.clone();
    url.pathname = "/";
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

export const config = {
  // Run on app pages, not on API proxying, Next internals, or static assets.
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico).*)"],
};
