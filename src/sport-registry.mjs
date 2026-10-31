// Capability inventory, not a claim of profitable markets or live models.
// Kalshi category evidence describes historical market availability, not current order books.
const research = (id, label, group, repo, priority = "Core", note = "") => ({
  id, label, group, priority, research: "Existing repository",
  repository: "https://github.com/chmoses98/" + repo, note
});
const discover = (id, label, group, priority = "Expansion", note = "", marketEvidence = null) => ({
  id, label, group, priority, research: "Needs research pipeline",
  repository: null, marketEvidence, note
});

export const SPORT_REGISTRY = [
  research("NFL", "NFL", "Football", "nfl-edge-finder"),
  research("CFB", "College Football (FBS)", "Football", "cfb-edge-finder", "Core", "Active Kalshi discovery and script research; former projection model retired. No validated wagering edge."),
  discover("CFB-FCS", "College Football (FCS)", "Football", "Expansion", "Kalshi has FCS markets; verify event and model coverage separately.", "https://kalshi.com/hubs/college-football"),
  research("NBA", "NBA", "Basketball", "nba-edge-finder"),
  research("CBB", "College Basketball (Men)", "Basketball", "cbb-edge-finder", "Core", "NCAA Division I men's model and market research; no demonstrated trading edge."),
  discover("CBB-W", "College Basketball (Women)", "Basketball", "Expansion", "Separate roster and matchup validation required."),
  discover("WNBA", "WNBA", "Basketball", "Expansion", "Do not transfer NBA model assumptions."),
  research("MLB", "MLB", "Baseball / Softball", "edge-finder-api"),
  discover("NCAA-BASEBALL", "NCAA Baseball", "Baseball / Softball", "Core", "2026 NCAA baseball game contracts exist on Kalshi; no dedicated SIFT model or capture pipeline yet.", "https://kalshi.com/markets/kxncaabbgame/college-baseball-game/kxncaabbgame-26may292100arsole"),
  discover("NCAA-SOFTBALL", "NCAA Softball", "Baseball / Softball", "Expansion", "Historical college softball contracts; no SIFT model built.", "https://kalshi.com/category/sports/baseball/college-softball/games"),
  research("NHL", "NHL", "Hockey", "NHL-edge-finder"),
  research("SOCCER", "Soccer (global)", "Soccer", "soccer-edge-finder", "Core", "Competition coverage must be checked league by league."),
  research("TENNIS", "Tennis (ATP / WTA)", "Racket Sports", "Tennis-Edge-Finder", "Core", "Keep tours and market formats separate."),
  discover("TABLE-TENNIS", "Table Tennis", "Racket Sports", "Exploratory", "Verify market identity and outcomes."),
  discover("BADMINTON", "Badminton", "Racket Sports", "Exploratory", "Verify suitable market and data sources."),
  discover("GOLF", "Golf (PGA / LPGA)", "Individual Sports", "Expansion", "Research field strength, cuts and placement.", "https://kalshi.com/category/sports/all-sports/all/combos"),
  discover("MMA", "MMA / UFC", "Combat Sports", "Expansion", "Opponent styles, weigh-ins and settlement.", "https://kalshi.com/category/sports/all-sports/all/combos"),
  discover("BOXING", "Boxing", "Combat Sports", "Expansion", "Judge decisions and fight outcomes.", "https://kalshi.com/category/sports/all-sports/all/combos"),
  discover("F1", "Formula 1 / Motorsport", "Motorsport", "Expansion", "Qualifying, penalties and race outcomes.", "https://kalshi.com/category/sports/all-sports/all/combos"),
  discover("ESPORTS", "Esports", "Esports", "Expansion", "Separate game title, league and format.", "https://kalshi.com/category/sports/all-sports/all/combos"),
  discover("CRICKET", "Cricket", "Global & Other", "Expansion", "Separate Test, ODI and T20.", "https://kalshi.com/category/sports/all-sports/all/combos"),
  discover("RUGBY", "Rugby", "Global & Other", "Exploratory", "Validate competitions, results and liquidity.", "https://kalshi.com/category/sports/all-sports/all/combos"),
  discover("LACROSSE", "Lacrosse", "Global & Other", "Exploratory", "Validate source data and order books.", "https://kalshi.com/category/sports/all-sports/all/combos"),
  discover("NCAA-VOLLEYBALL", "NCAA Volleyball (Women)", "Global & Other", "Expansion", "Match/set model and roster verification.", "https://kalshi.com/category/sports/all-sports/all/combos"),
  discover("DARTS", "Darts", "Global & Other", "Exploratory", "Tournament format and rules.", "https://kalshi.com/category/sports/all-sports/all/combos"),
  discover("CHESS", "Chess", "Global & Other", "Exploratory", "Draws and time controls.", "https://kalshi.com/category/sports/all-sports/all/combos"),
  discover("OLYMPICS", "Olympic & International Events", "Global & Other", "Exploratory", "Require independently verified event-specific data."),
  discover("OTHER", "Other / Newly Listed", "Global & Other", "Exploratory", "Record unclassified markets instead of silently dropping them.")
];
export const SPORT_GROUPS = [...new Set(SPORT_REGISTRY.map((sport) => sport.group))];
export const SPORTS = ["All sports", ...SPORT_REGISTRY.map((sport) => sport.id)];
export const CORE_SPORTS = SPORT_REGISTRY.filter((sport) => sport.priority === "Core");
export function sportById(id) { return SPORT_REGISTRY.find((sport) => sport.id === id) || null; }
export function sportLabel(id) { return sportById(id)?.label || id.replace(/^Custom: /, ""); }
export function isCustomSport(id) {
  return typeof id === "string" && /^Custom: [A-Za-z0-9][A-Za-z0-9 &/().'-]{1,59}$/.test(id);
}
export function registryStatus(sport) {
  return sport.research === "Existing repository" ? "Research repo exists" : "Research not built";
}
