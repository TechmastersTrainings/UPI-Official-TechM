export default function ReadinessList({ readiness }) {
  if (!readiness) return null;
  return (
    <ul className="checklist">
      {readiness.items.map((i) => (
        <li key={i.key} className={i.met ? 'is-met' : ''}>
          <span className="checklist__mark" aria-hidden="true">{i.met ? '✓' : '○'}</span>
          <span>
            {i.label}
            <span className="sr-only">{i.met ? ' (done)' : ' (not done)'}</span>
            {i.detail && <span className="checklist__detail">{i.detail}</span>}
          </span>
        </li>
      ))}
    </ul>
  );
}
