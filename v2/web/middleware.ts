import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

const COOKIE_NAME = process.env.FUNNEL_V2_SESSION_COOKIE_NAME || "funnel_v2_session";
const REQUIRE_AUTH = (process.env.FUNNEL_V2_WEB_REQUIRE_AUTH || "0").toLowerCase();
const AUTH_ENABLED = REQUIRE_AUTH === "1" || REQUIRE_AUTH === "true" || REQUIRE_AUTH === "yes" || REQUIRE_AUTH === "on";

export function middleware(request: NextRequest) {
  if (!AUTH_ENABLED) {
    return NextResponse.next();
  }
  const pathname = request.nextUrl.pathname;
  if (
    pathname === "/login" ||
    pathname.startsWith("/api/") ||
    pathname.startsWith("/_next/") ||
    pathname === "/favicon.ico"
  ) {
    return NextResponse.next();
  }
  const sessionCookie = request.cookies.get(COOKIE_NAME);
  if (sessionCookie?.value) {
    return NextResponse.next();
  }
  const loginUrl = new URL("/login", request.url);
  const nextValue = `${pathname}${request.nextUrl.search}`;
  if (nextValue && nextValue !== "/") {
    loginUrl.searchParams.set("next", nextValue);
  }
  loginUrl.searchParams.set("reason", "auth");
  return NextResponse.redirect(loginUrl);
}

export const config = {
  matcher: ["/((?!_next/static|_next/image).*)"],
};
