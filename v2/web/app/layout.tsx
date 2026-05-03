import "./globals.css";

import type { Metadata } from "next";
import type { ReactNode } from "react";

import { AppShell } from "../components/app-shell";
import { readCutoverState } from "../lib/runtime-state";
import { readWriteFreezeState } from "../lib/runtime-state";

export const metadata: Metadata = {
  title: "Stock Picking Funnel V2",
  description: "Zero-loss web migration workspace for Stock Picking Funnel.",
};

export const dynamic = "force-dynamic";

export default async function RootLayout({ children }: { children: ReactNode }) {
  const writeFreeze = await readWriteFreezeState();
  const cutoverState = await readCutoverState();
  return (
    <html lang="en">
      <body>
        <AppShell writeFreeze={writeFreeze} cutoverState={cutoverState}>
          {children}
        </AppShell>
      </body>
    </html>
  );
}
