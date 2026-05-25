export const metadata = {
  title: "Agent System",
  description: "Multi-LLM Agent System",
};

export default function RootLayout({ children }) {
  return (
    <html lang="pl">
      <body style={{ margin: 0, padding: 0, background: "#0a0a1a" }}>
        {children}
      </body>
    </html>
  );
}
