import "./globals.css";
import { BRAND } from "../src/theme";

export const metadata = {
  title: BRAND.name,
  description: "Player accounts and administration for the RimWorld Together multiplayer server.",
  icons: { icon: { url: "/rimworld-icon.png", type: "image/png" } },
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        <link
          href="https://fonts.googleapis.com/css2?family=Geist:wght@400..700&family=IBM+Plex+Mono:wght@400;500&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
