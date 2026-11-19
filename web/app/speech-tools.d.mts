export function selectRecorderMimeType(isTypeSupported: (type: string) => boolean, candidates?: string[]): string;
export function capTranscript(text: string, limit?: number): { text: string; truncated: boolean };
export function cleanSpeechText(text: string): string;
export function splitSpeechText(text: string, maxLength?: number): string[];
export function speechLangFor(language: string): string;
