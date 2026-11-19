export type ChartPlacement = { name: string; code: string; house: number; sign: string; retrograde: boolean };
export function parseChartFacts(facts?: string[]): { lagna: string; planets: ChartPlacement[] };
export function renderChartDiagramSvg(facts: string[], options?: { highlightHouses?: number[]; size?: 'small' | 'large'; language?: string; showLabels?: boolean; layout?: 'north' | 'south' }): string;
export function selectVisibleChartMessages(messages: Array<{ role: string; state?: string; questionId?: number; highlightedHouses?: number[] }>): boolean[];
export const houseLabels: Record<string, string[]>;
