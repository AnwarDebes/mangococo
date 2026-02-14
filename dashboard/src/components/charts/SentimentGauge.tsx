"use client";

interface SentimentGaugeProps {
  value: number; // 0-100
}

function getLabel(value: number): string {
  if (value <= 20) return "Extreme Fear";
  if (value <= 40) return "Fear";
  if (value <= 60) return "Neutral";
  if (value <= 80) return "Greed";
  return "Extreme Greed";
}

function getColor(value: number): string {
  if (value <= 20) return "#ef4444";
  if (value <= 40) return "#f97316";
  if (value <= 60) return "#eab308";
  if (value <= 80) return "#84cc16";
  return "#22c55e";
}

export default function SentimentGauge({ value }: SentimentGaugeProps) {
  const clampedValue = Math.max(0, Math.min(100, value));
  const angle = (clampedValue / 100) * 180 - 90; // -90 to 90 degrees
  const color = getColor(clampedValue);
  const label = getLabel(clampedValue);

  // SVG arc path
  const radius = 80;
  const cx = 100;
  const cy = 100;

  // Create arc segments for the gauge background
  const createArc = (
    startAngle: number,
    endAngle: number
  ): string => {
    const startRad = ((startAngle - 90) * Math.PI) / 180;
    const endRad = ((endAngle - 90) * Math.PI) / 180;
    const x1 = cx + radius * Math.cos(startRad);
    const y1 = cy + radius * Math.sin(startRad);
    const x2 = cx + radius * Math.cos(endRad);
    const y2 = cy + radius * Math.sin(endRad);
    const largeArc = endAngle - startAngle > 180 ? 1 : 0;
    return `M ${x1} ${y1} A ${radius} ${radius} 0 ${largeArc} 1 ${x2} ${y2}`;
  };

  // Needle position
  const needleAngle = ((angle) * Math.PI) / 180;
  const needleLength = 65;
  const needleX = cx + needleLength * Math.cos(needleAngle);
  const needleY = cy + needleLength * Math.sin(needleAngle);

  return (
    <div className="flex flex-col items-center">
      <svg viewBox="0 0 200 130" className="w-full max-w-[280px]">
        {/* Gauge arcs */}
        <path
          d={createArc(-90, -54)}
          fill="none"
          stroke="#ef4444"
          strokeWidth="12"
          strokeLinecap="round"
          opacity="0.6"
        />
        <path
          d={createArc(-50, -14)}
          fill="none"
          stroke="#f97316"
          strokeWidth="12"
          strokeLinecap="round"
          opacity="0.6"
        />
        <path
          d={createArc(-10, 10)}
          fill="none"
          stroke="#eab308"
          strokeWidth="12"
          strokeLinecap="round"
          opacity="0.6"
        />
        <path
          d={createArc(14, 50)}
          fill="none"
          stroke="#84cc16"
          strokeWidth="12"
          strokeLinecap="round"
          opacity="0.6"
        />
        <path
          d={createArc(54, 90)}
          fill="none"
          stroke="#22c55e"
          strokeWidth="12"
          strokeLinecap="round"
          opacity="0.6"
        />

        {/* Needle */}
        <line
          x1={cx}
          y1={cy}
          x2={needleX}
          y2={needleY}
          stroke={color}
          strokeWidth="3"
          strokeLinecap="round"
        />
        <circle cx={cx} cy={cy} r="6" fill={color} />
        <circle cx={cx} cy={cy} r="3" fill="#030712" />

        {/* Labels */}
        <text
          x="20"
          y="115"
          fill="#6b7280"
          fontSize="9"
          textAnchor="middle"
        >
          0
        </text>
        <text
          x="180"
          y="115"
          fill="#6b7280"
          fontSize="9"
          textAnchor="middle"
        >
          100
        </text>
      </svg>

      <div className="mt-2 text-center">
        <p className="text-3xl font-bold" style={{ color }}>
          {clampedValue}
        </p>
        <p className="text-sm font-medium" style={{ color }}>
          {label}
        </p>
      </div>
    </div>
  );
}
