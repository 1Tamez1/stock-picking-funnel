export function JsonPanel({ title, value }: { title: string; value: unknown }) {
  return (
    <section className="panel">
      <h2>{title}</h2>
      <pre className="json-block">{JSON.stringify(value, null, 2)}</pre>
    </section>
  );
}
