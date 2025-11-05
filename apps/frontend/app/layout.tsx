import type { Metadata } from "next";
import { Inter, Playfair_Display } from "next/font/google";
import "./globals.css";
import { ThemeProvider } from "next-themes";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });
const playfair = Playfair_Display({ subsets: ["latin"], variable: "--font-playfair" });

export const metadata: Metadata = {
  title: {
    default: "AlphaPilot — AI-powered portfolio management",
    template: "%s — AlphaPilot",
  },
  description:
    "Agentic portfolio management for institutions: realtime signals, policy-safe automation, and explainable decisions.",
  metadataBase: new URL("https://alphapilot.example.com"),
  openGraph: {
    title: "AlphaPilot — AI-powered portfolio management",
    description:
      "Agentic portfolio management for institutions: realtime signals, policy-safe automation, and explainable decisions.",
    url: "https://alphapilot.example.com",
    siteName: "AlphaPilot",
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "AlphaPilot — AI-powered portfolio management",
    description:
      "Agentic portfolio management for institutions: realtime signals, policy-safe automation, and explainable decisions.",
  },
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className={`${inter.variable} ${playfair.variable} antialiased`}>
        <ThemeProvider attribute="class" forcedTheme="dark">
          {children}
        </ThemeProvider>
      </body>
    </html>
  );
}
