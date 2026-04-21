import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Adaptive Prompt Elicitation",
  description: "Interactive text-to-image prompt elicitation via adaptive visual queries.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
