import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = { title: 'Melooha — Vedic astrology, made personal', description: 'Thoughtful Vedic readings, grounded in your chart facts.' };

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body className="min-h-screen bg-void font-body text-ink antialiased">{children}</body></html>;
}
