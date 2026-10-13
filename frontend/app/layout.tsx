import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "云仓运营助手",
  description: "基于虚构仓库数据的只读库存查询助手",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
