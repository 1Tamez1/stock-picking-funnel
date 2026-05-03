type LegacyParityFrameProps = {
  eyebrow: string;
  title: string;
  description: string;
  src: string;
};

export function LegacyParityFrame({ eyebrow, title, description, src }: LegacyParityFrameProps) {
  return (
    <section className="legacy-page">
      <header className="page-header legacy-page-header">
        <div>
          <p className="eyebrow">{eyebrow}</p>
          <h1>{title}</h1>
          <p>{description}</p>
        </div>
      </header>
      <div className="legacy-frame-wrap">
        <iframe className="legacy-frame" src={src} title={title} />
      </div>
    </section>
  );
}
