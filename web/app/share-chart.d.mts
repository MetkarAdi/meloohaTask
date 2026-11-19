export function createShareSvg(diagramSvg: string, options: { firstName?: string; facts: string[]; includeBirthDetails?: boolean; birthDetails?: string[] }): string;
export function svgToPng(svg: string, options?: { width?: number; height?: number }): Promise<Blob>;
