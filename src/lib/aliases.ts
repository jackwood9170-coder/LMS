/**
 * Team name aliases across all data sources:
 * football-data.co.uk, FPL API, The Odds API → canonical Supabase name.
 */
const ALIASES: Record<string, string> = {
  'Man United': 'Manchester United',
  'Man City': 'Manchester City',
  'Brighton': 'Brighton and Hove Albion',
  "Nott'm Forest": 'Nottingham Forest',
  'Newcastle': 'Newcastle United',
  'West Ham': 'West Ham United',
  'Wolves': 'Wolverhampton Wanderers',
  'Spurs': 'Tottenham Hotspur',
  'Tottenham': 'Tottenham Hotspur',
  'Leeds': 'Leeds United',
  'Leicester': 'Leicester City',
  'Norwich': 'Norwich City',
  'Ipswich': 'Ipswich Town',
  'Sheffield Weds': 'Sheffield Wednesday',
  'QPR': 'Queens Park Rangers',
  'Huddersfield': 'Huddersfield Town',
  'Cardiff': 'Cardiff City',
  'Stoke': 'Stoke City',
  'Swansea': 'Swansea City',
  'Coventry': 'Coventry City',
  'Brighton & Hove Albion': 'Brighton and Hove Albion',
  'Nottingham Forest': 'Nottingham Forest',
  'Wolverhampton': 'Wolverhampton Wanderers',
  'Sunderland AFC': 'Sunderland',
}

/**
 * Build a lookup: any outcome_name variant → team_id.
 * @param teamsMap  {teamId: teamName}
 */
export function buildAliasMap(
  teamsMap: Record<string, string>,
): Record<string, string> {
  const nameToId: Record<string, string> = {}
  for (const [tid, name] of Object.entries(teamsMap)) {
    nameToId[name] = tid
  }
  const aliasToId: Record<string, string> = { ...nameToId }
  for (const [alias, canonical] of Object.entries(ALIASES)) {
    if (canonical in nameToId && !(alias in aliasToId)) {
      aliasToId[alias] = nameToId[canonical]
    }
  }
  return aliasToId
}

/**
 * Find the price for a team in an odds outcomes dict,
 * regardless of which name variant was stored.
 */
export function findOutcomePrice(
  outcomes: Record<string, number>,
  teamId: string,
  aliasToId: Record<string, string>,
): number | null {
  for (const [outcomeName, price] of Object.entries(outcomes)) {
    if (aliasToId[outcomeName] === teamId) {
      return price
    }
  }
  return null
}
