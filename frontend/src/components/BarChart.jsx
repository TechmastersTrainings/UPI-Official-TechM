import { useState } from 'react';

/**
 * Dependency-free responsive SVG bar chart.
 * data: [{ key, label, value }]; formatValue formats tooltip/axis values.
 */
export default function BarChart({ data, formatValue = String, height = 220, ariaLabel }) {
  const [hover, setHover] = useState(null);
  const width = 720;
  const pad = { top: 12, right: 8, bottom: 26, left: 8 };
  const innerW = width - pad.left - pad.right;
  const innerH = height - pad.top - pad.bottom;
  const max = Math.max(1, ...data.map((d) => d.value));
  const slot = innerW / Math.max(1, data.length);
  const barW = Math.max(2, Math.min(28, slot * 0.68));
  const labelEvery = Math.ceil(data.length / 8);
  const allZero = data.every((d) => d.value === 0);

  return (
    <div className="chart">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={ariaLabel} preserveAspectRatio="none">
        {[0.25, 0.5, 0.75, 1].map((f) => (
          <line key={f} x1={pad.left} x2={width - pad.right} y1={pad.top + innerH * (1 - f)} y2={pad.top + innerH * (1 - f)} className="chart__grid" />
        ))}
        <line x1={pad.left} x2={width - pad.right} y1={pad.top + innerH} y2={pad.top + innerH} className="chart__axis" />
        {data.map((d, i) => {
          const h = (d.value / max) * innerH;
          const x = pad.left + slot * i + (slot - barW) / 2;
          return (
            <g key={d.key} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
              <rect x={pad.left + slot * i} y={pad.top} width={slot} height={innerH} fill="transparent" />
              <rect
                x={x}
                y={pad.top + innerH - h}
                width={barW}
                height={Math.max(h, d.value > 0 ? 2 : 0)}
                rx="3"
                className={hover === i ? 'chart__bar chart__bar--active' : 'chart__bar'}
              />
              {i % labelEvery === 0 && (
                <text x={pad.left + slot * i + slot / 2} y={height - 8} textAnchor="middle" className="chart__label">
                  {d.label}
                </text>
              )}
            </g>
          );
        })}
      </svg>
      <div className="chart__tooltip" aria-live="polite">
        {hover !== null ? (
          <>
            <strong>{data[hover].label}</strong> · {formatValue(data[hover].value)}
          </>
        ) : allZero ? (
          'No data in this period'
        ) : (
          `Peak ${formatValue(max)}`
        )}
      </div>
    </div>
  );
}
