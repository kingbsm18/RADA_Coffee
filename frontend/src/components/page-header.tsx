export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: string;
  actions?: React.ReactNode;
}) {
  return (
    <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">{title}</h1>
        {description && <p className="mt-1 max-w-3xl text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions}
    </div>
  );
}

export function ErrorBanner({ message }: { message: string }) {
  return (
    <p role="alert" className="mb-3 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
      {message}
    </p>
  );
}

export function EmptyState({ children }: { children: React.ReactNode }) {
  return <p className="rounded-lg border bg-card p-6 text-center text-sm text-muted-foreground">{children}</p>;
}

/** Explains a feature that needs a backend endpoint that does not exist yet. */
export function MissingBackend({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed bg-card p-4 text-sm">
      <p className="font-medium">{title}</p>
      <p className="mt-1 text-muted-foreground">{children}</p>
    </div>
  );
}
