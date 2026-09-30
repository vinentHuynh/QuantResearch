// Source snapshots keep their recorded names and hashes. Only presentation uses
// these cleaned titles, including the older catalog's misencoded middle dot.
export function strategyTitle(name: string): string {
  return name.replace(/^Pine\s*(?:\u00c2?\u00b7)\s*/, "");
}
