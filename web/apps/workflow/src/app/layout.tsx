import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Workflow Builder",
  description: "LangGraph-powered drag-and-drop workflow editor",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body style={{ margin: 0 }}>{children}</body>
    </html>
  );
}
