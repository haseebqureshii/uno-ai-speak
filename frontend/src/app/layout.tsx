import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Audio-First Socratic Language Tutor",
  description: "Drift-free, audio-first language tutoring powered by System 1 guardrails.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="antialiased transition dark:bg-slate-950 dark:text-slate-100">
        {children}
      </body>
    </html>
  );
}
