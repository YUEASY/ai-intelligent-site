export function formatUsd(cost: string): string {
  return `$${Number(cost).toFixed(6)}`;
}
