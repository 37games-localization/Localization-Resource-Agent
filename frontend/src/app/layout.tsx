import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "资源管理 MVP",
  description: "本地化资源管理自动化工作台"
};

export default function RootLayout({
  children
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
