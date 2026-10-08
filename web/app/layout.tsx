import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Business Hypothesis Analyst",
  description: "Create an analysis project and review its hypotheses.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
