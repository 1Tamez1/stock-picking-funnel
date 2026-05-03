import Link from "next/link";
import type { Route } from "next";
import type { ReactNode } from "react";

import { PageHeader } from "./page-header";

export function SurfaceHeader({
  eyebrow,
  title,
  description,
  legacyHref,
  actions,
}: {
  eyebrow: string;
  title: string;
  description: string;
  legacyHref: string;
  actions?: ReactNode;
}) {
  return (
    <PageHeader
      eyebrow={eyebrow}
      title={title}
      description={description}
      actions={
        <div className="header-actions">
          {actions}
          <Link href={legacyHref as Route} className="ghost-link">
            Legacy Surface
          </Link>
        </div>
      }
    />
  );
}
