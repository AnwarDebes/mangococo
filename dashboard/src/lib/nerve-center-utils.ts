import * as THREE from "three";

/**
 * Fibonacci sphere distribution — evenly spaces N points on a sphere surface.
 * Returns [x, y, z] for the i-th point (0-indexed) out of total points.
 */
export function fibonacciSphere(
  index: number,
  total: number,
  radius: number
): [number, number, number] {
  const goldenAngle = Math.PI * (3 - Math.sqrt(5));
  const y = 1 - (index / (total - 1)) * 2; // y goes from 1 to -1
  const radiusAtY = Math.sqrt(1 - y * y);
  const theta = goldenAngle * index;

  return [
    Math.cos(theta) * radiusAtY * radius,
    y * radius * 0.5, // flatten Y a bit
    Math.sin(theta) * radiusAtY * radius,
  ];
}

/**
 * Scale a price to a sphere radius in [minR, maxR]
 */
export function priceToRadius(
  price: number,
  minR = 0.3,
  maxR = 2.0
): number {
  if (price <= 0) return minR;
  const logVal = Math.log10(price + 1);
  // BTC ~$60k → log10 ~4.78, small coins ~$0.01 → log10 ~0
  const normalized = Math.min(logVal / 5, 1);
  return minR + normalized * (maxR - minR);
}

/**
 * Get color based on sentiment score (0-100)
 */
export function sentimentColor(score: number): string {
  if (score > 60) return "#22c55e"; // bullish green
  if (score < 40) return "#ef4444"; // bearish red
  return "#f59e0b"; // neutral amber
}

/**
 * Get signal action color
 */
export function signalColor(action: string): string {
  switch (action) {
    case "BUY":
      return "#22c55e";
    case "SELL":
      return "#ef4444";
    default:
      return "#f59e0b";
  }
}

/**
 * Generate circle points for orbital rings
 */
export function circlePoints(
  radius: number,
  segments = 64,
  y = 0
): THREE.Vector3[] {
  const points: THREE.Vector3[] = [];
  for (let i = 0; i <= segments; i++) {
    const angle = (i / segments) * Math.PI * 2;
    points.push(
      new THREE.Vector3(Math.cos(angle) * radius, y, Math.sin(angle) * radius)
    );
  }
  return points;
}

/**
 * Map a rank to a distance from center (lower rank = closer)
 */
export function rankToDistance(rank: number, maxDistance = 20): number {
  // rank 1 → close, rank 100 → far
  return 3 + (Math.min(rank, 50) / 50) * (maxDistance - 3);
}

/**
 * Pre-allocated Vector3 for reuse in useFrame loops
 */
export const tempVec3 = new THREE.Vector3();
export const tempVec3B = new THREE.Vector3();
