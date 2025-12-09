import type { Metadata } from "next";
import { Inter, Playfair_Display } from "next/font/google";
import "./globals.css";
import { ThemeProvider } from "next-themes";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });
const playfair = Playfair_Display({ subsets: ["latin"], variable: "--font-playfair" });

export const metadata: Metadata = {
  title: {
    default: "AgentInvest — AI-powered portfolio management",
    template: "%s — AgentInvest",
  },
  description:
    "Agentic portfolio management for institutions: realtime signals, policy-safe automation, and explainable decisions.",
  metadataBase: new URL("https://agentinvest.example.com"),
  openGraph: {
    title: "AgentInvest — AI-powered portfolio management",
    description:
      "Agentic portfolio management for institutions: realtime signals, policy-safe automation, and explainable decisions.",
    url: "https://agentinvest.example.com",
    siteName: "AgentInvest",
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "AgentInvest — AI-powered portfolio management",
    description:
      "Agentic portfolio management for institutions: realtime signals, policy-safe automation, and explainable decisions.",
  },
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script async src="https://www.googletagmanager.com/gtag/js?id=G-R1QZEMES4B"></script>
        <script
          dangerouslySetInnerHTML={{
            __html: `
              window.dataLayer = window.dataLayer || [];
              function gtag(){dataLayer.push(arguments);}
              gtag('js', new Date());
              gtag('config', 'G-R1QZEMES4B');
            `,
          }}
        />
      </head>
      <body className={`${inter.variable} ${playfair.variable} antialiased`}>
        <ThemeProvider attribute="class" forcedTheme="dark">
          {children}
        </ThemeProvider>
      </body>
    </html>
  );
}
