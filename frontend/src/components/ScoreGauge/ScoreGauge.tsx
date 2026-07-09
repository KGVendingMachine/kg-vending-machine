import styles from './ScoreGauge.module.css'

interface ScoreGaugeProps {
  score: number
  size?: number
}

function scoreColor(score: number): string {
  if (score >= 80) return 'var(--color-success)'
  if (score >= 60) return 'var(--color-warning)'
  return 'var(--color-danger)'
}

export function ScoreGauge({ score, size = 120 }: ScoreGaugeProps) {
  const strokeWidth = size * 0.1
  const radius = size / 2 - strokeWidth / 2
  const circumference = 2 * Math.PI * radius
  const offset = circumference * (1 - score / 100)
  const color = scoreColor(score)

  return (
    <div className={styles.gauge} style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="var(--color-border)"
          strokeWidth={strokeWidth}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
        />
      </svg>
      <div className={styles.value}>
        <span
          className={styles.score}
          style={{ color, fontSize: size * 0.28 }}
        >
          {score}
        </span>
        <span className={styles.max}>/ 100</span>
      </div>
    </div>
  )
}
