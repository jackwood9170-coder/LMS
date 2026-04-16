const ELO_SCALE = 400

/**
 * ELO 1X2 model with draw boundary.
 * Returns probabilities as fractions (0–1).
 */
export function elo1x2(
  ratingHome: number,
  ratingAway: number,
  hfa: number,
  drawBoundary: number,
): { home: number; draw: number; away: number } {
  const dr = ratingHome + hfa - ratingAway
  const pHome = 1 / (1 + Math.pow(10, -(dr - drawBoundary) / ELO_SCALE))
  const pAway = 1 / (1 + Math.pow(10, (dr + drawBoundary) / ELO_SCALE))
  const pDraw = 1 - pHome - pAway
  return { home: pHome, draw: pDraw, away: pAway }
}

/**
 * De-vig decimal odds via basic normalisation.
 * Returns probabilities as fractions (0–1).
 */
export function devig(
  oddsH: number,
  oddsD: number,
  oddsA: number,
): { home: number; draw: number; away: number } {
  const invH = 1 / oddsH
  const invD = 1 / oddsD
  const invA = 1 / oddsA
  const overround = invH + invD + invA
  return {
    home: invH / overround,
    draw: invD / overround,
    away: invA / overround,
  }
}
